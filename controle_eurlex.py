#!/usr/bin/env python3
"""
Diagnostic du découpage des textes EUR-Lex (aucun appel réseau).
Utilisation :  python controle_eurlex.py
Lit donnees\\eurlex\\*.json et affiche, pour chaque texte : numéros en double, suite des
numéros, premiers articles, exemples de doublons.
"""

import json
from collections import Counter
from pathlib import Path

dossier = Path("donnees") / "eurlex"
fichiers = sorted(dossier.glob("*.json"))
if not fichiers:
    raise SystemExit("Aucun fichier dans donnees\\eurlex")

for f in fichiers:
    if f.name == "resume_eurlex.json":
        continue
    d = json.loads(f.read_text(encoding="utf-8"))
    arts = d["articles"]
    nums = [a["numero"] for a in arts]
    c = Counter(nums)
    doublons = {n: k for n, k in c.items() if k > 1}
    print("=" * 70)
    print(f"{d['celex']} — {len(arts)} articles | numéros distincts : {len(c)} | numéros en double : {len(doublons)}")
    print(f"Préambule : {len(d.get('preambule', ''))} caractères ; début : {d.get('preambule', '')[:90]!r}")

    # Suite des 60 premiers numéros, pour voir où ça se perd
    print("Suite des 60 premiers numéros :", " ".join(nums[:60]))

    # Premiers articles
    for a in arts[:3]:
        print(f"   art. {a['numero']} | titre : {a['titre'][:70]!r} | texte : {len(a['texte'])} car. | {a['texte'][:80]!r}")

    # Articles très courts (souvent des renvois pris pour des débuts d'article)
    courts = [a for a in arts if len(a["texte"]) < 40]
    print(f"Articles de moins de 40 caractères : {len(courts)}")
    for a in courts[:5]:
        print(f"   art. {a['numero']} | titre : {a['titre'][:60]!r} | {a['texte']!r}")

    # Exemples de doublons
    for n in list(doublons)[:3]:
        print(f"   doublon « {n} » ({doublons[n]} fois) :")
        for a in [x for x in arts if x["numero"] == n][:2]:
            print(f"      titre : {a['titre'][:60]!r} | texte : {len(a['texte'])} car. | {a['texte'][:70]!r}")

    # Où se situent les « retours en arrière » de numérotation
    precedent, retours = 0, []
    for i, n in enumerate(nums):
        try:
            v = int("".join(ch for ch in n if ch.isdigit()))
        except ValueError:
            continue
        if v < precedent - 5:
            retours.append((i, precedent, v))
        precedent = v
    print(f"Retours en arrière de numérotation : {len(retours)}", retours[:6])

print("\nCopiez-collez ce résultat à Claude.")
