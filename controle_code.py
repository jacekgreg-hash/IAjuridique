#!/usr/bin/env python3
"""
Contrôle d'un code téléchargé par code_generique.py : états des articles et dates de fin de validité.

Utilisation :   python controle_code.py cpp
Lit      :  donnees\\code_<nom>_articles.json
Écrit    :  donnees\\controle_etats_<nom>.txt
"""

import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

nom = sys.argv[1] if len(sys.argv) > 1 else "cpp"
chemin = Path("donnees") / f"code_{nom}_articles.json"
if not chemin.exists():
    sys.exit(f"Fichier introuvable : {chemin}")
articles = json.loads(chemin.read_text(encoding="utf-8"))


def en_date(v):
    """Dates Légifrance : millisecondes depuis 1970 (négatives avant 1970, 2999-01-01 = pas de fin)."""
    if isinstance(v, (int, float)):
        return (datetime(1970, 1, 1) + timedelta(milliseconds=v)).date().isoformat()
    return v


for a in articles:
    a["date_debut"], a["date_fin"] = en_date(a.get("date_debut")), en_date(a.get("date_fin"))
aujourd_hui = date.today().isoformat()
out = [f"Articles : {len(articles)} | état au {aujourd_hui}",
       "États : " + " | ".join(f"{k}: {v}" for k, v in Counter(a["etat"] for a in articles).most_common())]

for etat in sorted({a["etat"] for a in articles}, key=str):
    lot = [a for a in articles if a["etat"] == etat]
    fins = Counter((a["date_fin"] or "aucune")[:4] for a in lot)
    passes = sum(1 for a in lot if a["date_fin"] and a["date_fin"] <= aujourd_hui)
    futurs = sum(1 for a in lot if a["date_fin"] and aujourd_hui < a["date_fin"] < "2900")
    sans_fin = sum(1 for a in lot if a["date_fin"] and a["date_fin"] >= "2900")
    out.append(f"\n=== État {etat} ({len(lot)} articles) ===")
    out.append(f"Date de fin passée : {passes} | future : {futurs} | 2999 (sans fin prévue) : {sans_fin} | aucune : {fins.get('aucune', 0)}")
    out.append("Années de fin : " + " | ".join(f"{k}: {v}" for k, v in sorted(fins.items())[:15]))
    out.append("Années de début : " + " | ".join(f"{k}: {v}" for k, v in sorted(Counter(
        (a['date_debut'] or 'aucune')[:4] for a in lot).items())[-8:]))
    pas = max(1, len(lot) // 6)
    for a in lot[::pas][:6]:
        out.append(f"   art. {a['num']} | {a['date_debut']} → {a['date_fin']} | {(a['texte'] or '')[:110]!r}")

nums = Counter(str(a["num"]) for a in articles)
doubles = [n for n, c in nums.items() if c > 1]
out.append(f"\nNuméros présents plusieurs fois : {len(doubles)} {doubles[:12]}")
texte = "\n".join(out)
Path("donnees", f"controle_etats_{nom}.txt").write_text(texte, encoding="utf-8")
print(texte)
print(f"\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\controle_etats_{nom}.txt).")
