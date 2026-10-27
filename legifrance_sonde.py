#!/usr/bin/env python3
"""
Sonde de l'API Légifrance pour la jurisprudence constitutionnelle (fond CONSTIT) et administrative (fond CETAT).
Ne télécharge presque rien : quelques recherches et une lecture de décision, pour vérifier que les accès fonctionnent
et voir la forme des réponses avant d'écrire le téléchargement complet.

Utilisation (mêmes variables d'environnement PISTE) :   python legifrance_sonde.py
Écrit :  donnees\\sonde_legifrance.txt
"""

import json
import sys

import prototype_ingestion as pi

EXPRESSIONS = ["droits de la défense", "douane"]
FONDS = [("CONSTIT", "Conseil constitutionnel"), ("CETAT", "Conseil d'État (JADE)")]
CONSULT = ["/consult/juri", "/consult/constit", "/consult/cetat"]


def recherche(fond, expression, page=1, taille=5):
    corps = {"fond": fond, "recherche": {
        "champs": [{"typeChamp": "ALL", "operateur": "ET",
                    "criteres": [{"typeRecherche": "EXACTE", "valeur": expression, "operateur": "ET"}]}],
        "filtres": [], "pageNumber": page, "pageSize": taille, "operateur": "ET",
        "sort": "PERTINENCE", "typePagination": "DEFAUT"}}
    return pi.appeler("POST", pi.LEGIFRANCE_BASE + "/search", json=corps)


def main():
    out = []
    for fond, nom in FONDS:
        out.append(f"\n=== {nom} (fond {fond}) ===")
        premier = None
        for expression in EXPRESSIONS + ["zzqxwvk"]:
            rep = recherche(fond, expression)
            if rep.status_code != 200:
                out.append(f"  « {expression} » : échec {rep.status_code} {rep.text[:200]!r}")
                continue
            j = rep.json()
            total = j.get("totalResultNumber")
            out.append(f"  « {expression} » : {total} résultats | clés de la réponse : {sorted(j)[:8]}")
            res = j.get("results") or []
            if res:
                out.append(f"      clés d'un résultat : {sorted(res[0])[:12]}")
                titres = res[0].get("titles") or []
                out.append(f"      premier résultat : {json.dumps(titres[:1], ensure_ascii=False)[:260]}")
                if premier is None and titres:
                    premier = titres[0].get("id")
        if premier:
            out.append(f"  Lecture de la décision {premier} :")
            for chemin in CONSULT:
                rep = pi.appeler("POST", pi.LEGIFRANCE_BASE + chemin, json={"textId": premier})
                if rep.status_code == 200:
                    j = rep.json()
                    texte = json.dumps(j, ensure_ascii=False)
                    out.append(f"    {chemin} : OK | clés {sorted(j)[:10]} | {len(texte)} caractères")
                    out.append(f"      début : {texte[:300]!r}")
                    break
                out.append(f"    {chemin} : {rep.status_code} {rep.text[:120]!r}")
    texte = "\n".join(out)
    pi.DOSSIER_SORTIE.mkdir(exist_ok=True)
    (pi.DOSSIER_SORTIE / "sonde_legifrance.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\sonde_legifrance.txt).")


if __name__ == "__main__":
    sys.exit(main())
