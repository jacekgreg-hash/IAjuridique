#!/usr/bin/env python3
"""
Diagnostic des textes de doctrine extraits (avant découpage et construction du corpus).

Utilisation :   python da_diagnostic.py
Lit      :  donnees\\bod\\textes_manifest.json, donnees\\bod\\textes\\*.txt
Écrit    :  donnees\\bod\\controle_diagnostic.txt
Répond à trois questions :
  1. Les textes très courts / OCR faibles sont-ils des coquilles vides (titre seul) ou des pertes ?
  2. Combien de fichiers contiennent plusieurs textes (« texte n° ... ») à découper ?
  3. Quelle est la répartition des tailles (pour calibrer le découpage en passages) ?
"""

import json
import re
from collections import Counter
from pathlib import Path

DOSSIER = Path("donnees") / "bod"
TEXTES = DOSSIER / "textes"
NUM = re.compile(r"\b[Tt]exte\s+n\s*[°ºo]\s*:?\s*(\d{2}-\d{3})", re.IGNORECASE)


def lire(ident):
    p = TEXTES / f"{ident}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def court(t, n=170):
    return re.sub(r"\s+", " ", t)[:n]


def main():
    manifeste = json.loads((DOSSIER / "textes_manifest.json").read_text(encoding="utf-8"))
    out = ["Statuts : " + " | ".join(f"{k}: {v}" for k, v in Counter(r["statut"] for r in manifeste).most_common())]

    # 1. textes courts / faibles
    peu = [r for r in manifeste if r["statut"] in ("court", "ocr_faible")]
    out.append(f"\n=== 1. Textes courts ou OCR faible ({len(peu)}) ===")
    tailles = Counter()
    for r in peu:
        n = r.get("caracteres", 0)
        tailles["< 50" if n < 50 else "50-100" if n < 100 else "100-200" if n < 200 else "> 200"] += 1
    out.append("Tailles : " + " | ".join(f"{k}: {v}" for k, v in tailles.items()))
    par_dec = Counter(((r["date_publication"] or "????")[:3] + "0") for r in peu)
    out.append("Par décennie : " + " | ".join(f"{k}: {v}" for k, v in sorted(par_dec.items())))
    pas = max(1, len(peu) // 25)
    for r in peu[::pas][:25]:
        out.append(f"  {r['id']} ({r['statut']}, {r.get('caracteres', 0)} car., {r.get('pages')} p.) "
                   f"titre DA : {(r.get('titre') or '')[:70]!r} | texte : {court(lire(r['id']))!r}")

    # 2. fichiers à plusieurs textes
    out.append("\n=== 2. Fichiers contenant plusieurs « texte n° » ===")
    multi, nb_par_fichier, vides = [], Counter(), 0
    for r in manifeste:
        if r["statut"] not in ("ok", "ok_ocr"):
            continue
        t = lire(r["id"])
        nums = []
        for m in NUM.finditer(t):
            if m.group(1) not in nums:
                nums.append(m.group(1))
        nb_par_fichier[min(len(nums), 6)] += 1
        if len(nums) > 1:
            multi.append((r, nums, len(t)))
        if not nums:
            vides += 1
    out.append("Nombre de numéros distincts par fichier (6 = 6 ou plus) : " +
               " | ".join(f"{k}: {v}" for k, v in sorted(nb_par_fichier.items())))
    out.append(f"Fichiers sans aucune mention « texte n° » : {vides}")
    out.append(f"Fichiers avec plusieurs numéros : {len(multi)}")
    for r, nums, n in sorted(multi, key=lambda x: -len(x[1]))[:12]:
        out.append(f"  DA {r['id']} ({r['date_publication']}) : {len(nums)} numéros {nums[:6]} | {n} car. | "
                   f"numéro propre présent : {r['id'] in nums}")

    # 3. tailles
    out.append("\n=== 3. Tailles des textes (caractères) ===")
    tx = sorted(r.get("caracteres", 0) for r in manifeste if r["statut"] in ("ok", "ok_ocr"))
    if tx:
        q = lambda p: tx[min(len(tx) - 1, int(len(tx) * p))]
        out.append(f"Médiane {q(0.5):,} | 90e centile {q(0.9):,} | 99e centile {q(0.99):,} | maximum {tx[-1]:,}".replace(",", " "))
        gros = [r for r in manifeste if r.get("caracteres", 0) > 300000]
        out.append(f"Fichiers de plus de 300 000 caractères : {len(gros)} " + str([(r['id'], r['caracteres']) for r in gros[:8]]))
    texte = "\n".join(out)
    (DOSSIER / "controle_diagnostic.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\bod\\controle_diagnostic.txt).")


if __name__ == "__main__":
    main()
