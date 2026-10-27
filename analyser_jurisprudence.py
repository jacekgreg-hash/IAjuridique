#!/usr/bin/env python3
"""
Contrôle de la jurisprudence téléchargée (aucun appel réseau).

Utilisation :  python analyser_jurisprudence.py [FICHIER.jsonl]
Par défaut :   donnees\\jurisprudence_cassation.jsonl

Vérifie que les décisions parlent bien de douane : présence réelle des expressions
« code des douanes » / « administration des douanes » dans le texte, année par année,
et montre quelques exemples.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

chemin = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("donnees") / "jurisprudence_cassation.jsonl"
if not chemin.exists():
    sys.exit(f"Fichier introuvable : {chemin}")


def normaliser(t):
    return (t or "").lower().replace("’", "'").replace("\xa0", " ")


total = 0
ids = Counter()
sans_texte = 0
presence = Counter()               # présence globale de chaque expression
par_annee = defaultdict(lambda: Counter())
themes_douane = 0
bulletin = 0
exemples_aucune, exemples_ad_seule = [], []
longueurs = []

with chemin.open(encoding="utf-8") as f:
    for ligne in f:
        if not ligne.strip():
            continue
        try:
            d = json.loads(ligne)
        except ValueError:
            continue
        total += 1
        ids[d.get("id")] += 1
        texte = normaliser(d.get("text"))
        if not texte:
            sans_texte += 1
        longueurs.append(len(texte))

        cd = "code des douanes" in texte
        ad = "administration des douanes" in texte
        mot = "douane" in texte
        presence["code des douanes"] += cd
        presence["administration des douanes"] += ad
        presence["l'une ou l'autre"] += (cd or ad)
        presence["aucune des deux"] += (not (cd or ad))
        presence["mot « douane » absent du texte"] += (not mot)

        chambre = d.get("chamber") or "?"
        annee = str(d.get("decision_date") or "????")[:4]
        c = par_annee[(chambre, annee)]
        c["n"] += 1
        c["cd"] += cd
        c["ad"] += ad
        c["aucune"] += (not (cd or ad))

        themes = d.get("themes") or []
        if any("douane" in str(t).lower() for t in themes):
            themes_douane += 1
        if d.get("publication"):
            bulletin += 1

        info = {
            "id": d.get("id"), "date": d.get("decision_date"), "chambre": chambre,
            "themes": [str(t) for t in themes[:3]],
            "resume": (d.get("summary") or "")[:110].replace("\n", " "),
            "debut": texte[:110].replace("\n", " "),
        }
        if not (cd or ad) and total % 40 == 0 and len(exemples_aucune) < 8:
            exemples_aucune.append(info)
        if ad and not cd and total % 40 == 0 and len(exemples_ad_seule) < 6:
            exemples_ad_seule.append(info)

print(f"Fichier : {chemin} ({chemin.stat().st_size / 1e6:.0f} Mo)")
print(f"Décisions : {total} | identifiants distincts : {len(ids)} | doublons : {total - len(ids)}")
print(f"Sans texte : {sans_texte} | longueur moyenne du texte : {sum(longueurs) // max(1, len(longueurs))} caractères")
print(f"Avec un thème contenant « douane » : {themes_douane} | publiées au bulletin : {bulletin}")
print("\nPrésence réelle des expressions dans le texte des décisions :")
for k, v in presence.items():
    print(f"   {k:34s} {v:6d}  ({100 * v / max(1, total):.0f} %)")

print("\nPar chambre et par année : décisions | « code des douanes » | « administration des douanes » | aucune des deux")
for chambre in sorted({k[0] for k in par_annee}):
    print(f"  --- chambre {chambre} ---")
    for (ch, annee), c in sorted(par_annee.items()):
        if ch == chambre:
            print(f"   {annee} : {c['n']:4d} | {c['cd']:4d} | {c['ad']:4d} | {c['aucune']:4d}")

print("\nExemples de décisions SANS aucune des deux expressions dans le texte :")
for e in exemples_aucune:
    print(f"   {e['date']} {e['chambre']} {e['id']} | thèmes : {e['themes']} | {e['resume'] or e['debut']}")
print("\nExemples de décisions avec seulement « administration des douanes » :")
for e in exemples_ad_seule:
    print(f"   {e['date']} {e['chambre']} {e['id']} | thèmes : {e['themes']} | {e['resume'] or e['debut']}")
print("\nCopiez-collez ce résultat à Claude.")
