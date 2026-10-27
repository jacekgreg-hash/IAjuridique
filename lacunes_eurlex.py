#!/usr/bin/env python3
"""Cherche les numéros d'articles manquants dans les textes EUR-Lex découpés (hors réseau).
Utilisation :  python lacunes_eurlex.py"""

import json
import re
from pathlib import Path

for f in sorted((Path("donnees") / "eurlex").glob("3*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    nums = [a["numero"] for a in d["articles"]]
    entiers = [int(re.match(r"\d+", n).group()) for n in nums]
    manquants = [n for n in range(1, max(entiers) + 1) if n not in set(entiers)]
    suffixes = [n for n in nums if " " in n]
    print(f"{d['celex']} : {len(nums)} articles, de 1 à {max(entiers)} | manquants : {manquants} | avec suffixe : {suffixes}")
    for m in manquants:
        # montre ce qui précède l'endroit du trou
        prec = [a for a in d["articles"] if int(re.match(r"\d+", a["numero"]).group()) == m - 1]
        if prec:
            fin = prec[-1]["texte"]
            print(f"   fin de l'article {m - 1} : ...{fin[-300:]!r}")
print("\nCopiez-collez ce résultat à Claude.")
