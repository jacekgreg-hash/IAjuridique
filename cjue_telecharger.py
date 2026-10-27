#!/usr/bin/env python3
"""
Téléchargement de la jurisprudence de la Cour de justice et du Tribunal de l'UE portant sur les
textes douaniers (version française), via l'Office des publications de l'UE (accès public, sans clé).

Utilisation :  python cjue_telecharger.py
Résultats dans  donnees\\cjue\\ :
   liste.json            liste des décisions retenues (CELEX, date, type, liens, textes concernés, pertinence)
   cjue_douane.jsonl     une décision par ligne, avec le texte intégral
   echecs.json           décisions dont le texte n'a pas pu être récupéré
Reprise possible : les décisions déjà enregistrées ne sont pas retéléchargées.
"""

import json
import sys
import time
from pathlib import Path

import requests

from ingestion_eurlex import Texte  # extraction du texte d'une page HTML

DOSSIER = Path("donnees") / "cjue"
POINT_ACCES = "https://publications.europa.eu/webapi/rdf/sparql"
ACTES = ["31992R2913", "31993R2454", "32013R0952", "32015R2446", "32015R2447", "31987R2658", "32016R0341"]
TYPES = {"CJ": "arrêt de la Cour", "TJ": "arrêt du Tribunal", "CC": "conclusions de l'avocat général",
         "CO": "ordonnance"}
LIENS_FORTS = ("interpretes", "requests_interpretation", "states_failure", "declares_")

REQUETE = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?celex (MIN(?date) AS ?date)
       (GROUP_CONCAT(DISTINCT STR(?lien); separator="|") AS ?liens)
       (GROUP_CONCAT(DISTINCT STR(?celexActe); separator="|") AS ?actes)
WHERE {
  ?acte cdm:resource_legal_id_celex ?celexActe .
  FILTER(STR(?celexActe) IN (%s))
  ?oeuvre ?lien ?acte .
  ?oeuvre cdm:resource_legal_id_celex ?celex .
  FILTER(REGEX(STR(?celex), "^6[0-9]{4}(CJ|TJ|CC|CO)"))
  OPTIONAL { ?oeuvre cdm:work_date_document ?date }
} GROUP BY ?celex ORDER BY ?celex
""" % ", ".join('"%s"' % a for a in ACTES)


def pertinence(liens):
    return "forte" if any(any(f in l for f in LIENS_FORTS) for l in liens) else "moyenne"


def lister():
    r = requests.post(POINT_ACCES, data={"query": REQUETE},
                      headers={"Accept": "application/sparql-results+json",
                               "User-Agent": "ia-juridique-prototype/0.1"}, timeout=600)
    if r.status_code != 200:
        sys.exit(f"Liste impossible (code {r.status_code}) : {r.text[:400]}")
    liste = []
    for b in r.json()["results"]["bindings"]:
        celex = b["celex"]["value"]
        liens = [x.split("#")[-1] for x in b["liens"]["value"].split("|") if x]
        liste.append({
            "celex": celex,
            "date": b.get("date", {}).get("value", "")[:10],
            "type": TYPES.get(celex[5:7], celex[5:7]),
            "liens": sorted(set(liens)),
            "textes_douaniers": sorted(set(b["actes"]["value"].split("|"))),
            "pertinence": pertinence(liens),
        })
    return liste


def telecharger(celex):
    modeles = [
        ("https://publications.europa.eu/resource/celex/%s",
         {"Accept": "application/xhtml+xml, text/html;q=0.9", "Accept-Language": "fra"}),
        ("https://eur-lex.europa.eu/legal-content/FR/TXT/HTML/?uri=CELEX:%s",
         {"Accept": "text/html", "Accept-Language": "fr"}),
    ]
    dernier = "aucune réponse"
    for modele, entetes in modeles:
        url = modele % celex
        for _ in range(3):
            try:
                r = requests.get(url, headers={**entetes, "User-Agent": "ia-juridique-prototype/0.1"}, timeout=90)
            except requests.RequestException as e:
                dernier = f"{url} : {e}"
                time.sleep(3)
                continue
            if r.status_code == 200 and len(r.content) > 3000:
                return r.content, url
            dernier = f"{url} : code {r.status_code}, {len(r.content)} octets"
            if r.status_code in (200, 202, 429, 500, 502, 503):
                time.sleep(4)
                continue
            break
    return None, dernier


def main():
    DOSSIER.mkdir(parents=True, exist_ok=True)
    chemin_liste = DOSSIER / "liste.json"
    if chemin_liste.exists():
        liste = json.loads(chemin_liste.read_text(encoding="utf-8"))
        print(f"Liste déjà établie : {len(liste)} décisions")
    else:
        print("Établissement de la liste (service SPARQL)…")
        liste = lister()
        chemin_liste.write_text(json.dumps(liste, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Liste : {len(liste)} décisions "
              f"(fortes : {sum(1 for x in liste if x['pertinence'] == 'forte')}, "
              f"moyennes : {sum(1 for x in liste if x['pertinence'] == 'moyenne')})")

    fichier = DOSSIER / "cjue_douane.jsonl"
    deja = set()
    if fichier.exists():
        for ligne in fichier.read_text(encoding="utf-8").splitlines():
            if ligne.strip():
                try:
                    deja.add(json.loads(ligne)["celex"])
                except (ValueError, KeyError):
                    pass
        print(f"Reprise : {len(deja)} décisions déjà enregistrées")

    echecs = []
    restantes = [x for x in liste if x["celex"] not in deja]
    print(f"À télécharger : {len(restantes)}")
    with fichier.open("a", encoding="utf-8") as sortie:
        for k, d in enumerate(restantes, 1):
            contenu, source = telecharger(d["celex"])
            if contenu is None:
                echecs.append({"celex": d["celex"], "détail": source})
            else:
                analyseur = Texte()
                analyseur.feed(contenu.decode("utf-8", errors="replace"))
                texte = "\n".join(analyseur.fin())
                sortie.write(json.dumps({**d, "source": source, "texte": texte}, ensure_ascii=False) + "\n")
                sortie.flush()
            if k % 50 == 0:
                print(f"  {k}/{len(restantes)} traitées, {len(echecs)} échecs")
            time.sleep(0.4)
    (DOSSIER / "echecs.json").write_text(json.dumps(echecs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTerminé : {len(restantes) - len(echecs)} téléchargées, {len(echecs)} échecs "
          f"(détail dans {DOSSIER / 'echecs.json'})")
    print("Copiez-collez ce résultat à Claude.")


if __name__ == "__main__":
    main()
