#!/usr/bin/env python3
"""Cherche l'article 245 du règlement 2026/2108 dans le fichier téléchargé (hors réseau).
Utilisation :  python chercher_article_245.py"""

import re
from pathlib import Path

chemin = Path("donnees") / "eurlex" / "32026R2108.html"
html = chemin.read_text(encoding="utf-8", errors="replace")
texte = re.sub(r"<[^>]+>", "\n", html)
texte = re.sub(r"[ \t\xa0]+", " ", texte)
lignes = [l.strip() for l in texte.splitlines() if l.strip()]

print(f"Fichier : {chemin} ({len(lignes)} lignes de texte)")
trouve = False
for i, l in enumerate(lignes):
    if "Auditeur des données" in l or re.match(r"^Article\s+24[4-6]\b", l):
        trouve = True
        print(f"\n--- ligne {i} ---")
        for j in range(max(0, i - 2), min(len(lignes), i + 6)):
            print(f"   {j}: {lignes[j][:150]!r}")
if not trouve:
    print("Rien trouvé autour de l'article 245.")
print("\nCopiez-collez ce résultat à Claude.")
