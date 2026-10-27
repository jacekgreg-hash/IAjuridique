#!/usr/bin/env python3
"""
Comptage (sans téléchargement) des arrêts de la Cour de justice de l'Union européenne
et du Tribunal portant sur la douane, via le service de données ouvertes de l'Office des
publications (point d'accès SPARQL, public, sans clé).

Utilisation :  python cjue_compter.py
Résultat aussi enregistré dans donnees\\cjue_comptage.txt
"""

import json
import sys
from pathlib import Path

import requests

POINT_ACCES = "https://publications.europa.eu/webapi/rdf/sparql"
LIBELLES = ["douane", "union douanière", "code des douanes", "droits de douane", "dette douanière",
            "valeur en douane", "tarif douanier commun", "régime douanier", "origine des marchandises",
            "contrebande", "fraude douanière", "nomenclature tarifaire"]

REQUETE = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?an (COUNT(DISTINCT ?oeuvre) AS ?n) WHERE {
  ?concept skos:prefLabel ?etiquette .
  FILTER(LANG(?etiquette) = "fr" && LCASE(STR(?etiquette)) IN (%s))
  ?oeuvre cdm:work_is_about_concept_eurovoc ?concept .
  ?oeuvre cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(STR(?celex), "6") && REGEX(STR(?celex), "^6[0-9]{4}(CJ|TJ|CC|CO|CN)"))
  ?oeuvre cdm:work_date_document ?date .
  BIND(YEAR(?date) AS ?an)
} GROUP BY ?an ORDER BY ?an
""" % ", ".join('"%s"' % x for x in LIBELLES)


def main():
    print("Interrogation du service de l'Office des publications de l'UE…")
    try:
        r = requests.post(POINT_ACCES, data={"query": REQUETE},
                          headers={"Accept": "application/sparql-results+json",
                                   "User-Agent": "ia-juridique-prototype/0.1"}, timeout=180)
    except requests.RequestException as e:
        sys.exit(f"Échec de connexion : {e}")
    print(f"Code de réponse : {r.status_code}")
    if r.status_code != 200:
        sys.exit("Réponse inattendue : " + r.text[:500])
    lignes = r.json()["results"]["bindings"]
    sortie = ["Arrêts, ordonnances et conclusions (Cour et Tribunal) liés à la douane, par année :"]
    total = 0
    for l in lignes:
        an, n = l["an"]["value"], int(l["n"]["value"])
        total += n
        sortie.append(f"   {an} : {n}")
    sortie.append(f"Total (une œuvre peut compter pour plusieurs thèmes, mais est comptée une fois par année) : {total}")
    texte = "\n".join(sortie)
    Path("donnees").mkdir(exist_ok=True)
    (Path("donnees") / "cjue_comptage.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude.")


if __name__ == "__main__":
    main()
