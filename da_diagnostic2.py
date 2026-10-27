#!/usr/bin/env python3
"""
Diagnostic n°2 : fichiers partagés entre plusieurs DA et structure des fichiers à plusieurs « texte n° ».

Utilisation :   python da_diagnostic2.py
Lit      :  donnees\\bod\\textes_manifest.json, donnees\\bod\\textes\\*.txt
Écrit    :  donnees\\bod\\controle_diagnostic2.txt
"""

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

DOSSIER = Path("donnees") / "bod"
TEXTES = DOSSIER / "textes"
NUM = re.compile(r"\b[Tt]exte\s+n\s*[°ºo]\s*:?\s*(\d{2}-\d{3})", re.IGNORECASE)
CHOIX = ["97-144", "98-198", "01-117", "01-139", "01-040", "99-058"]


def lire(i):
    p = TEXTES / f"{i}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main():
    man = [r for r in json.loads((DOSSIER / "textes_manifest.json").read_text(encoding="utf-8"))
           if r["statut"] in ("ok", "ok_ocr")]
    out = []

    # A. textes identiques partagés entre plusieurs DA
    groupes = defaultdict(list)
    for r in man:
        t = re.sub(r"\s+", " ", lire(r["id"])).strip()
        groupes[hashlib.md5(t.encode()).hexdigest()].append(r["id"])
    partages = [g for g in groupes.values() if len(g) > 1]
    out.append(f"=== A. Textes identiques partagés par plusieurs DA ===")
    out.append(f"Fichiers lus : {len(man)} | textes distincts : {len(groupes)} | groupes de doublons : {len(partages)} "
               f"| fichiers concernés : {sum(len(g) for g in partages)}")
    out.append("Taille des groupes : " + " | ".join(f"{k} DA: {v}" for k, v in sorted(Counter(len(g) for g in partages).items())))
    for g in sorted(partages, key=len, reverse=True)[:8]:
        out.append(f"  {len(g)} DA : {sorted(g)[:8]}")

    # B. structure autour des mentions « texte n° »
    out.append("\n=== B. Contexte des mentions « texte n° » dans des fichiers multi-textes ===")
    for ident in CHOIX:
        t = lire(ident)
        if not t:
            out.append(f"\n--- DA {ident} : texte absent")
            continue
        ms = list(NUM.finditer(t))
        out.append(f"\n--- DA {ident} : {len(t)} car., {len(ms)} mentions")
        pas = max(1, len(ms) // 7)
        for m in ms[::pas][:7]:
            a, b = max(0, m.start() - 90), min(len(t), m.end() + 90)
            out.append(f"   @{m.start():>7} : …{re.sub(chr(10), ' ⏎ ', t[a:b])}…")
        out.append(f"   début du fichier : {re.sub(chr(10), ' ⏎ ', t[:220])!r}")
    texte = "\n".join(out)
    (DOSSIER / "controle_diagnostic2.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\bod\\controle_diagnostic2.txt).")


if __name__ == "__main__":
    main()
