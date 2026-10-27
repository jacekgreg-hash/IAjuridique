#!/usr/bin/env python3
"""
Second comptage (sans téléchargement) : décisions de la Cour de justice / du Tribunal reliées
aux textes douaniers de l'Union (via le service SPARQL public de l'Office des publications).

Utilisation :  python cjue_compter2.py
Résultat aussi enregistré dans donnees\\cjue_comptage2.txt
"""

import sys
from pathlib import Path

import requests

POINT_ACCES = "https://publications.europa.eu/webapi/rdf/sparql"
ACTES = ["31992R2913", "31993R2454", "32013R0952", "32015R2446", "32015R2447", "31987R2658", "32016R0341",
         "31991R2913"]
LISTE = ", ".join('"%s"' % a for a in ACTES)

ENTETE = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
"""
BLOC = """
  ?acte cdm:resource_legal_id_celex ?celexActe .
  FILTER(STR(?celexActe) IN (%s))
  ?oeuvre ?lien ?acte .
  ?oeuvre cdm:resource_legal_id_celex ?celex .
  FILTER(REGEX(STR(?celex), "^6[0-9]{4}(CJ|TJ|CC|CO|CN|CA)"))
""" % LISTE

REQUETES = {
    "Par type de lien (pour comprendre quelle relation existe)": ENTETE + """
SELECT ?lien (COUNT(DISTINCT ?oeuvre) AS ?n) WHERE {""" + BLOC + """
} GROUP BY ?lien ORDER BY DESC(?n)""",
    "Par texte douanier concerné": ENTETE + """
SELECT ?celexActe (COUNT(DISTINCT ?oeuvre) AS ?n) WHERE {""" + BLOC + """
} GROUP BY ?celexActe ORDER BY DESC(?n)""",
    "Par année (toutes relations confondues)": ENTETE + """
SELECT ?an (COUNT(DISTINCT ?oeuvre) AS ?n) WHERE {""" + BLOC + """
  ?oeuvre cdm:work_date_document ?date .
  BIND(YEAR(?date) AS ?an)
} GROUP BY ?an ORDER BY ?an""",
}


def interroger(requete):
    r = requests.post(POINT_ACCES, data={"query": requete},
                      headers={"Accept": "application/sparql-results+json",
                               "User-Agent": "ia-juridique-prototype/0.1"}, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"code {r.status_code} : {r.text[:300]}")
    return r.json()["results"]["bindings"]


def main():
    sortie = []
    for titre, requete in REQUETES.items():
        sortie.append(f"\n=== {titre} ===")
        try:
            lignes = interroger(requete)
        except Exception as e:
            sortie.append(f"   ÉCHEC : {e}")
            continue
        if not lignes:
            sortie.append("   (aucun résultat)")
        total = 0
        for l in lignes:
            cle = [v["value"] for k, v in l.items() if k != "n"][0]
            n = int(l["n"]["value"])
            total += n
            sortie.append(f"   {cle.split('#')[-1]} : {n}")
        sortie.append(f"   (somme des lignes : {total})")
    texte = "\n".join(sortie)
    Path("donnees").mkdir(exist_ok=True)
    (Path("donnees") / "cjue_comptage2.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude.")


if __name__ == "__main__":
    sys.exit(main())
