#!/usr/bin/env python3
"""Affiche les dispositions finales du règlement 2026/2108 et l'en-tête de ses annexes (hors réseau).
Utilisation :  python lire_application.py
Résultat aussi enregistré dans donnees\\eurlex\\dispositions_finales_2026_2108.txt"""

import json
import re
from pathlib import Path

d = json.loads((Path("donnees") / "eurlex" / "32026R2108.json").read_text(encoding="utf-8"))
sortie = []

sortie.append("=== DERNIERS ARTICLES (de 280 à 287) ===")
for a in d["articles"]:
    if int(re.match(r"\d+", a["numero"]).group()) >= 280:
        sortie.append(f"\n--- Article {a['numero']} — {a['titre']} ---\n{a['texte']}")

annexes = d.get("annexes", "").splitlines()
sortie.append("\n\n=== ANNEXES : lignes d'en-tête ===")
sortie.append(f"({len(annexes)} lignes au total)")
sortie.append("\n".join(annexes[:40]))

sortie.append("\n\n=== ANNEXES : titres repérés (ANNEXE / Tableau / Correspondance) ===")
for i, l in enumerate(annexes):
    if re.match(r"^(ANNEXE|Annexe|TABLEAU|Tableau)\b", l) or "orrespondance" in l:
        sortie.append(f"   ligne {i}: {l[:140]}")

texte = "\n".join(sortie)
(Path("donnees") / "eurlex" / "dispositions_finales_2026_2108.txt").write_text(texte, encoding="utf-8")
print(texte)
print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\eurlex\\dispositions_finales_2026_2108.txt).")
