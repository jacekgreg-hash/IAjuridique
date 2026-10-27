#!/usr/bin/env python3
"""
Jurisprudence constitutionnelle (Conseil constitutionnel) et administrative (Conseil d'État, cours administratives
d'appel, tribunaux administratifs publiés dans JADE) via l'API Légifrance.

Constat de la sonde : la recherche renvoie bien 0 résultat pour une expression absurde, mais, comme pour Judilibre,
on ne présume pas qu'elle respecte les expressions exactes : le tri définitif se fait hors ligne, sur le texte intégral.

Utilisation (mêmes variables d'environnement PISTE) :
   python legifrance_jurisprudence.py compter constit        # compte seulement
   python legifrance_jurisprudence.py telecharger constit    # Conseil constitutionnel (quelques centaines de décisions)
   python legifrance_jurisprudence.py compter cetat
   python legifrance_jurisprudence.py telecharger cetat      # JADE : décisions mentionnant la douane (milliers)
Reprise automatique si le script s'interrompt (relancer la même commande).

Écrit :  donnees\\juri_<fond>.jsonl, donnees\\juri_<fond>_tags.json, donnees\\juri_<fond>_cache.json,
         donnees\\controle_juri_<fond>.txt
"""

import json
import re
import sys
import time
from collections import Counter

import requests

import prototype_ingestion as pi

FONDS = {
    "constit": {
        "fond": "CONSTIT", "prefixe": "CONSTEXT", "nom": "Conseil constitutionnel",
        "expressions": ["droits de la défense", "douane", "procès-verbal", "droit de se taire", "garde à vue",
                        "visite domiciliaire", "procès équitable", "inviolabilité du domicile"],
    },
    "cetat": {
        "fond": "CETAT", "prefixe": "CETATEXT", "nom": "Conseil d'État et juridictions administratives (JADE)",
        "expressions": ["code des douanes", "administration des douanes", "douane"],
    },
}
TAILLE = [100]          # taille de page ; réduite automatiquement si l'API la refuse
MARQUES = re.compile(r"</?mark>")


class ErreurReseau(Exception):
    pass


def appel(chemin, corps):
    for essai in range(5):
        try:
            return pi.appeler("POST", pi.LEGIFRANCE_BASE + chemin, json=corps)
        except requests.exceptions.RequestException:
            print(f"    erreur réseau (essai {essai + 1}/5), nouvelle tentative dans {5 * (essai + 1)} s")
            time.sleep(5 * (essai + 1))
    raise ErreurReseau()


def recherche(fond, expression, page):
    corps = {"fond": fond, "recherche": {
        "champs": [{"typeChamp": "ALL", "operateur": "ET",
                    "criteres": [{"typeRecherche": "EXACTE", "valeur": expression, "operateur": "ET"}]}],
        "filtres": [], "pageNumber": page, "pageSize": TAILLE[0], "operateur": "ET",
        "sort": "PERTINENCE", "typePagination": "DEFAUT"}}
    rep = appel("/search", corps)
    if rep.status_code == 400 and TAILLE[0] > 20:
        TAILLE[0] = 50 if TAILLE[0] > 50 else 20
        print(f"    taille de page refusée, nouvel essai avec {TAILLE[0]}")
        return recherche(fond, expression, page)
    return rep


def lister(cfg, expression):
    """Renvoie ({id: titre}, complet ?) pour une expression."""
    trouvees, page = {}, 1
    while True:
        rep = recherche(cfg["fond"], expression, page)
        if rep.status_code != 200:
            print(f"    recherche en échec ({rep.status_code}) : {rep.text[:150]!r}")
            return trouvees, False
        j = rep.json()
        res = j.get("results") or []
        for r in res:
            for t in r.get("titles") or []:
                if str(t.get("id", "")).startswith(cfg["prefixe"]):
                    trouvees[t["id"]] = MARQUES.sub("", str(t.get("title") or ""))
                    break
        if not res or page * TAILLE[0] >= (j.get("totalResultNumber") or 0) or page >= 300:
            return trouvees, True
        page += 1


def main():
    args = sys.argv[1:]
    if len(args) != 2 or args[0] not in ("compter", "telecharger") or args[1] not in FONDS:
        sys.exit(__doc__)
    mode, cle = args
    cfg = FONDS[cle]
    pi.DOSSIER_SORTIE.mkdir(exist_ok=True)
    d = pi.DOSSIER_SORTIE
    f_cache, f_tags, f_sortie = d / f"juri_{cle}_cache.json", d / f"juri_{cle}_tags.json", d / f"juri_{cle}.jsonl"

    temoin, _ = lister(cfg, "zzqxwvk")
    if temoin:
        sys.exit("Contrôle échoué : une expression absurde renvoie des résultats. Arrêt.")
    print(f"Contrôle réussi. {cfg['nom']} — mode : {mode}.")

    cache = json.loads(f_cache.read_text(encoding="utf-8")) if f_cache.exists() else {}
    tags, titres, echecs_recherche = {}, {}, []
    par_expression = {}
    for expression in cfg["expressions"]:
        if expression in cache:
            trouvees = cache[expression]
        else:
            try:
                trouvees, complet = lister(cfg, expression)
            except ErreurReseau:
                echecs_recherche.append(expression)
                continue
            if not complet:
                echecs_recherche.append(expression)
                continue
            cache[expression] = trouvees
            f_cache.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        par_expression[expression] = len(trouvees)
        print(f"  « {expression} » : {len(trouvees)} décisions")
        for ident, titre in trouvees.items():
            titres[ident] = titre
            tags.setdefault(ident, []).append(expression)

    nouvelles = echecs = 0
    if mode == "telecharger":
        deja = set()
        if f_sortie.exists():
            for ligne in f_sortie.read_text(encoding="utf-8").splitlines():
                try:
                    deja.add(json.loads(ligne)["id"])
                except (ValueError, KeyError):
                    pass
            print(f"  reprise : {len(deja)} décisions déjà enregistrées")
        a_faire = [i for i in titres if i not in deja]
        print(f"  {len(a_faire)} décisions à télécharger")
        with f_sortie.open("a", encoding="utf-8") as sortie:
            for k, ident in enumerate(a_faire, 1):
                try:
                    rep = appel("/consult/juri", {"textId": ident})
                except ErreurReseau:
                    echecs += 1
                    continue
                if rep.status_code != 200:
                    echecs += 1
                    print(f"    échec {ident} ({rep.status_code})")
                    continue
                sortie.write(json.dumps({"id": ident, "fond": cfg["fond"], "titre": titres[ident],
                                         "recherches": tags[ident], "decision": rep.json().get("text")},
                                        ensure_ascii=False) + "\n")
                sortie.flush()
                nouvelles += 1
                if k % 200 == 0:
                    print(f"    {k}/{len(a_faire)}")
    f_tags.write_text(json.dumps(tags, ensure_ascii=False), encoding="utf-8")

    annees = Counter()
    for t in titres.values():
        m = re.findall(r"\b(19\d{2}|20\d{2})\b", t)
        annees[(m[-1][:3] + "0") if m else "????"] += 1
    out = [f"{cfg['nom']} : décisions distinctes trouvées : {len(titres)} | téléchargées maintenant : {nouvelles} "
           f"| échecs : {echecs} | recherches échouées : {echecs_recherche}",
           "Par expression : " + " | ".join(f"{k}: {v}" for k, v in par_expression.items()),
           "Par décennie (année lue dans le titre) : " + " | ".join(f"{k}: {v}" for k, v in sorted(annees.items())),
           "\n=== Exemples de titres ==="]
    out += [f"   {i} | {t[:150]}" for i, t in list(titres.items())[:: max(1, len(titres) // 10)][:10]]
    texte = "\n".join(out)
    (d / f"controle_juri_{cle}.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print(f"\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\controle_juri_{cle}.txt).")


if __name__ == "__main__":
    main()
