#!/usr/bin/env python3
"""
Tri de la jurisprudence téléchargée (aucun appel réseau, fichier d'origine intact).

Utilisation :  python filtrer_jurisprudence.py [FICHIER.jsonl]
Par défaut :   donnees\\jurisprudence_cassation.jsonl
Résultat :     donnees\\jurisprudence_cassation_douane.jsonl

Ne garde que les décisions dont le texte parle de douane, avec un niveau de pertinence :
  forte   = le texte contient « code des douanes »
  moyenne = « administration des douanes » (sans « code des douanes »)
  faible  = mention de « douan... » seulement (agents des douanes, droits de douane, douanier...)
Les décisions sans aucune mention sont écartées (elles restent dans le fichier d'origine).
"""

import json
import sys
from collections import Counter
from pathlib import Path

source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("donnees") / "jurisprudence_cassation.jsonl"
if not source.exists():
    sys.exit(f"Fichier introuvable : {source}")
sortie_chemin = source.with_name(source.stem + "_douane.jsonl")


def normaliser(t):
    return (t or "").lower().replace("’", "'").replace("\xa0", " ")


compte = Counter()
par_annee = Counter()
total = 0
with source.open(encoding="utf-8") as f, sortie_chemin.open("w", encoding="utf-8") as sortie:
    for ligne in f:
        if not ligne.strip():
            continue
        try:
            d = json.loads(ligne)
        except ValueError:
            continue
        total += 1
        texte = normaliser(d.get("text"))
        if "code des douanes" in texte:
            niveau = "forte"
        elif "administration des douanes" in texte:
            niveau = "moyenne"
        elif "douan" in texte:
            niveau = "faible"
        else:
            compte["écartée"] += 1
            continue
        d["pertinence_douane"] = niveau
        compte[niveau] += 1
        par_annee[str(d.get("decision_date") or "????")[:4]] += 1
        sortie.write(json.dumps(d, ensure_ascii=False) + "\n")

gardees = total - compte["écartée"]
print(f"Décisions lues : {total}")
print(f"Gardées : {gardees}  (forte : {compte['forte']} | moyenne : {compte['moyenne']} | faible : {compte['faible']})")
print(f"Écartées (aucune mention de douane) : {compte['écartée']}")
print(f"Fichier créé : {sortie_chemin} ({sortie_chemin.stat().st_size / 1e6:.0f} Mo)")
print("\nGardées par année :")
print("   " + " | ".join(f"{a}: {n}" for a, n in sorted(par_annee.items())))
print("\nCopiez-collez ce résultat à Claude.")
