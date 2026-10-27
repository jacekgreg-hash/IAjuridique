#!/usr/bin/env python3
"""
Jurisprudence « générale » utile au contentieux douanier : nullité des procès-verbaux, droits de la défense,
procédure et preuve. Source : Judilibre (Cour de cassation), décisions PUBLIÉES par défaut (Bulletin, rapport,
lettre de chambre, communiqué), toutes chambres utiles : criminelle, commerciale, chambre mixte, assemblée plénière.

Utilisation (mêmes variables d'environnement que prototype_ingestion.py) :
   python jurisprudence_generale.py compter             # compte seulement (rien n'est téléchargé), décisions publiées
   python jurisprudence_generale.py compter toutes      # idem, en incluant les décisions non publiées
   python jurisprudence_generale.py                     # télécharge (publiées) ; reprise possible
   python jurisprudence_generale.py telecharger toutes  # télécharge aussi les non publiées (volume bien plus grand)

Reprise : si le script s'interrompt (délai réseau, etc.), relancez la même commande : il repart du cache.
Écrit :  donnees\\jurisprudence_generale.jsonl        décisions complètes (une par ligne)
         donnees\\jurisprudence_generale_tags.json    pour chaque décision, les expressions qui l'ont fait trouver
         donnees\\controle_jurisprudence_generale.txt
"""

import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date

import requests

import prototype_ingestion as pi

THEMES = {
    "nullité des procès-verbaux": [
        "nullité du procès-verbal", "nullité des procès-verbaux", "procès-verbal de constatation",
        "foi due aux procès-verbaux", "procès-verbaux font foi jusqu'à inscription de faux",
        "inscription de faux", "article 429 du code de procédure pénale",
        "article 802 du code de procédure pénale", "nullité substantielle", "grief",
    ],
    "droits de la défense": [
        "droits de la défense", "droit de se taire", "assistance d'un avocat", "notification des droits",
        "droit à un procès équitable", "principe du contradictoire", "article 6 de la Convention européenne",
        "égalité des armes", "audition libre", "retenue douanière",
    ],
    "procédure et preuve": [
        "loyauté de la preuve", "visite domiciliaire", "garde à vue", "article 63 du code des douanes",
        "article 64 du code des douanes", "article 334 du code des douanes", "article 323 du code des douanes",
        "article 324 du code des douanes", "prescription de l'action publique", "ne bis in idem",
    ],
}
# cr : criminelle ; comm : commerciale ; mi : chambre mixte ; pl : assemblée plénière
CHAMBRES = [("cc", "cr"), ("cc", "comm"), ("cc", "mi"), ("cc", "pl")]
PUBLICATIONS = ["b", "r", "l", "c"]
ANNEE_DEBUT = 1990
DOSSIER = pi.DOSSIER_SORTIE
FICHIER = DOSSIER / "jurisprudence_generale.jsonl"
TAGS = DOSSIER / "jurisprudence_generale_tags.json"
CACHE = DOSSIER / "jurisprudence_generale_cache.json"   # résultats de recherche déjà obtenus (reprise rapide)


class ErreurReseau(Exception):
    pass


def requete(expression, juridiction, chambre, annee, publiees, page):
    p = {"query": expression, "operator": "exact", "jurisdiction": juridiction, "chamber": chambre,
         "date_start": f"{annee}-01-01", "date_end": f"{annee}-12-31", "page_size": 50, "page": page}
    if publiees:
        p["publication"] = PUBLICATIONS
    for essai in range(5):
        try:
            return pi.rechercher_judilibre(p)
        except requests.exceptions.RequestException:
            print(f"    délai dépassé ou erreur réseau (essai {essai + 1}/5), nouvelle tentative dans {5 * (essai + 1)} s")
            time.sleep(5 * (essai + 1))
    raise ErreurReseau()


def chercher(expression, juridiction, chambre, annee, publiees):
    """Renvoie (décisions trouvées, recherche complète ?). Une recherche incomplète n'est pas mise en cache."""
    trouvees, page = {}, 0
    while True:
        res = requete(expression, juridiction, chambre, annee, publiees, page)
        if not res:
            return trouvees, False
        for r in res.get("results", []):
            trouvees[r["id"]] = {k: r.get(k) for k in ("chamber", "publication", "decision_date")}
        page += 1
        if page * 50 >= res.get("total", 0) or page >= 199:
            return trouvees, True


def main():
    args = sys.argv[1:]
    compter = bool(args) and args[0] == "compter"
    publiees = "toutes" not in args
    pi.DOSSIER_SORTIE.mkdir(exist_ok=True)

    # contrôle : une expression absurde doit donner 0 résultat (sinon les totaux n'ont aucun sens)
    temoin = requete("zzqxwvk", "cc", "cr", date.today().year - 1, publiees, 0)
    if temoin is None or temoin.get("total", 0) != 0:
        sys.exit("Contrôle échoué : la recherche d'une expression absurde ne renvoie pas 0 résultat. Arrêt.")
    print(f"Contrôle réussi. Périmètre : {'décisions publiées' if publiees else 'toutes les décisions'}, "
          f"depuis {ANNEE_DEBUT}. Mode : {'comptage' if compter else 'téléchargement'}.")

    deja = set()
    if FICHIER.exists():
        for ligne in FICHIER.read_text(encoding="utf-8").splitlines():
            try:
                deja.add(json.loads(ligne)["id"])
            except (ValueError, KeyError):
                pass
    tags = json.loads(TAGS.read_text(encoding="utf-8")) if TAGS.exists() else {}
    vues = {}                                  # id -> résultat de recherche (métadonnées)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    echecs_recherche = []
    par_expression = defaultdict(set)
    nouvelles = echecs = 0
    sortie = None if compter else FICHIER.open("a", encoding="utf-8")
    try:
        for juridiction, chambre in CHAMBRES:
            for annee in range(ANNEE_DEBUT, date.today().year + 1):
                trouvees = {}
                for theme, expressions in THEMES.items():
                    for expression in expressions:
                        cle = f"{chambre}|{annee}|{int(publiees)}|{expression}"
                        if cle in cache:
                            resultats = cache[cle]
                        else:
                            try:
                                resultats, complet = chercher(expression, juridiction, chambre, annee, publiees)
                            except ErreurReseau:
                                echecs_recherche.append((chambre, annee, expression))
                                continue
                            if not complet:
                                echecs_recherche.append((chambre, annee, expression))
                                continue
                            cache[cle] = resultats
                        for ident, r in resultats.items():
                            trouvees[ident] = r
                            par_expression[(theme, expression)].add(ident)
                            tags.setdefault(ident, [])
                            if expression not in tags[ident]:
                                tags[ident].append(expression)
                CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                vues.update(trouvees)
                if trouvees:
                    print(f"  {chambre} {annee} : {len(trouvees)} décisions")
                if compter:
                    continue
                for ident in [i for i in trouvees if i not in deja]:
                    rep = pi.appeler("GET", pi.JUDILIBRE_BASE + "/decision", params={"id": ident})
                    if rep.status_code != 200:
                        echecs += 1
                        print(f"    échec {ident} ({rep.status_code})")
                        continue
                    sortie.write(json.dumps(rep.json(), ensure_ascii=False) + "\n")
                    sortie.flush()
                    deja.add(ident)
                    nouvelles += 1
                TAGS.write_text(json.dumps(tags, ensure_ascii=False), encoding="utf-8")
    finally:
        if sortie:
            sortie.close()
    if not compter:
        TAGS.write_text(json.dumps(tags, ensure_ascii=False), encoding="utf-8")

    out = [f"Décisions distinctes trouvées : {len(vues)} | nouvelles téléchargées : {nouvelles} | échecs de téléchargement : {echecs}",
           f"Recherches échouées (à relancer, la reprise est automatique) : {len(echecs_recherche)} {echecs_recherche[:6]}"]
    out.append("Par chambre : " + " | ".join(f"{k}: {v}" for k, v in Counter(
        r.get("chamber") for r in vues.values()).most_common()))
    out.append("Par niveau de publication : " + " | ".join(f"{k}: {v}" for k, v in Counter(
        str(r.get("publication")) for r in vues.values()).most_common()))
    out.append("Par décennie : " + " | ".join(f"{k}: {v}" for k, v in sorted(Counter(
        (str(r.get("decision_date") or "????")[:3] + "0") for r in vues.values()).items())))
    out.append("\n=== Décisions trouvées par expression ===")
    for (theme, expression), ids in sorted(par_expression.items(), key=lambda x: (x[0][0], -len(x[1]))):
        out.append(f"   [{theme}] {expression} : {len(ids)}")
    texte = "\n".join(out)
    (DOSSIER / "controle_jurisprudence_generale.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\controle_jurisprudence_generale.txt).")


if __name__ == "__main__":
    main()
