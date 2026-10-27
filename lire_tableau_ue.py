#!/usr/bin/env python3
"""Examine le tableau de correspondance en annexe du règlement 2026/2108 (hors réseau).
Utilisation :  python lire_tableau_ue.py
Résultat aussi enregistré dans donnees\\eurlex\\tableau_correspondance_apercu.txt"""

import json
import re
from collections import Counter
from pathlib import Path

d = json.loads((Path("donnees") / "eurlex" / "32026R2108.json").read_text(encoding="utf-8"))
lignes = d.get("annexes", "").splitlines()
debut = next((i for i, l in enumerate(lignes) if "TABLEAU DE CORRESPONDANCE" in l.upper()), 0)
tableau = lignes[debut:]

sortie = [f"Tableau : {len(tableau)} lignes à partir de la ligne {debut} des annexes", "",
          "=== 70 premières lignes ==="]
sortie += [f"{i:4d}: {l[:160]}" for i, l in enumerate(tableau[:70])]

autres = [l for l in tableau[8:] if not re.match(r"^Article\b", l)]
sortie += ["", f"=== Lignes qui ne commencent pas par « Article » (hors en-tête) : {len(autres)} ==="]
for texte, n in Counter(autres).most_common(25):
    sortie.append(f"   {n:4d} × {texte[:150]}")

sortie += ["", "=== Lignes « Article » : exemples avec plusieurs articles, alinéas ou points ==="]
longues = [l for l in tableau if l.startswith("Article") and (";" in l or " et " in l or "à" in l.split(",")[-1])]
sortie += [f"   {l[:170]}" for l in longues[:15]]
sortie.append(f"(nombre de lignes « Article » : {sum(1 for l in tableau if l.startswith('Article'))})")

texte = "\n".join(sortie)
(Path("donnees") / "eurlex" / "tableau_correspondance_apercu.txt").write_text(texte, encoding="utf-8")
print(texte)
print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\eurlex\\tableau_correspondance_apercu.txt).")
