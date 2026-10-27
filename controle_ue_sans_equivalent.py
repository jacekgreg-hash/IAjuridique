#!/usr/bin/env python3
"""Affiche les intitulés des articles UE sans équivalent dans la concordance (hors réseau).
Utilisation :  python controle_ue_sans_equivalent.py
Résultat aussi enregistré dans donnees\\eurlex\\controle_sans_equivalent.txt"""

import json
from pathlib import Path

D = Path("donnees") / "eurlex"
conc = json.loads((D / "concordance_ue.json").read_text(encoding="utf-8"))
ancien = {int(a["numero"].split()[0]): a for a in json.loads((D / "32013R0952.json").read_text(encoding="utf-8"))["articles"]}
nouveau = {int(a["numero"].split()[0]): a for a in json.loads((D / "32026R2108.json").read_text(encoding="utf-8"))["articles"]}

sortie = ["=== ARTICLES DE L'ANCIEN CODE (952/2013) SANS ÉQUIVALENT ==="]
for n, v in conc["ancien_vers_nouveau"].items():
    if v["statut"].startswith("sans équivalent"):
        a = ancien.get(int(n))
        sortie.append(f"   art. {n} — {a['titre'][:90] if a else '?'}")

sortie += ["", "=== ARTICLES DU NOUVEAU CODE (2026/2108) SANS ANCIEN ÉQUIVALENT DANS LE TABLEAU ==="]
for n, v in conc["nouveau_vers_ancien"].items():
    if not v["correspondances"]:
        a = nouveau.get(int(n))
        sortie.append(f"   art. {n} — {a['titre'][:90] if a else '?'}")

texte = "\n".join(sortie)
(D / "controle_sans_equivalent.txt").write_text(texte, encoding="utf-8")
print(texte)
print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\eurlex\\controle_sans_equivalent.txt).")
