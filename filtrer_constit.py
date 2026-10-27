#!/usr/bin/env python3
"""
Tri hors ligne des décisions du Conseil constitutionnel téléchargées (aucun appel réseau, fichier d'origine intact).

Constat : la recherche « procès-verbal » ramenait surtout des décisions de contentieux électoral (AN, SEN, PDR...),
sans rapport. On ne garde que les décisions de constitutionnalité (QPC, DC, L, LP...) qui traitent de la douane ou
des garanties de procédure, en lisant le texte intégral.

Utilisation :  python filtrer_constit.py
Lit      :  donnees\\juri_constit.jsonl
Écrit    :  donnees\\juri_constit_filtree.jsonl  (champs ajoutés : niveau, motifs, texte_brut), donnees\\controle_filtre_constit.txt
Niveau A = mention de la douane ; niveau B = garanties de procédure seules.
"""

import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

source = Path("donnees") / "juri_constit.jsonl"
if not source.exists():
    sys.exit(f"Fichier introuvable : {source}")
sortie_chemin = source.with_name("juri_constit_filtree.jsonl")

NATURES_GARDEES = ("QPC", "DC", "LP", "L", "LOM", "FNR", "I", "ORGA")   # lues dans le titre
DOUANE = re.compile(r"code des douanes|agents? des douanes|administration des douanes|\bdouanes?\b|douanier")
MOTIFS = [
    ("droits de la défense", r"droits? de la d[ée]fense"),
    ("droit de se taire", r"droit de se taire|garder le silence|droit au silence"),
    ("article 16 DDHC / procès équitable", r"article 16 de la d[ée]claration|proc[èe]s [ée]quitable|recours juridictionnel effectif"),
    ("nécessité et proportionnalité des peines", r"n[ée]cessit[ée] des d[ée]lits et des peines|proportionnalit[ée] des peines|article 8 de la d[ée]claration"),
    ("présomption d'innocence", r"pr[ée]somption d'innocence"),
    ("visites domiciliaires / perquisitions", r"visites? domiciliaires?|inviolabilit[ée] du domicile|perquisitions?"),
    ("procès-verbaux", r"proc[èe]s-verba(?:l|ux)"),
    ("garde à vue / assistance d'un avocat", r"garde [àa] vue|assistance d'un avocat"),
]
COMPILES = [(e, re.compile(p)) for e, p in MOTIFS]


def textes(o):
    """Toutes les chaînes d'un objet JSON imbriqué."""
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from textes(v)
    elif isinstance(o, list):
        for v in o:
            yield from textes(v)


def texte_brut(decision):
    plus_long = max(textes(decision), key=len, default="")
    t = html.unescape(re.sub(r"<[^>]+>", " ", plus_long))
    return re.sub(r"\s+", " ", t.lower().replace("’", "'").replace("\xa0", " ")).strip()


def nature(titre):
    m = re.search(r"\b\d{2,4}-\d+(?:/\d+)* ([A-Z]+)\b", titre or "")
    return m.group(1) if m else None


compte, par_nature, par_motif, longueurs = Counter(), Counter(), Counter(), []
with source.open(encoding="utf-8") as f, sortie_chemin.open("w", encoding="utf-8") as sortie:
    for ligne in f:
        if not ligne.strip():
            continue
        d = json.loads(ligne)
        n = nature(d.get("titre"))
        par_nature[str(n)] += 1
        if n not in NATURES_GARDEES:
            compte["écartées (électoral, etc.)"] += 1
            continue
        t = texte_brut(d.get("decision"))
        longueurs.append(len(t))
        motifs = [e for e, rx in COMPILES if rx.search(t)]
        douane = bool(DOUANE.search(t))
        if not douane and not motifs:
            compte["écartées (aucun motif)"] += 1
            continue
        d["niveau"] = "A" if douane else "B"
        d["motifs"] = motifs
        d["texte_brut"] = t
        compte["gardées niveau " + d["niveau"]] += 1
        for e in motifs:
            par_motif[e] += 1
        sortie.write(json.dumps(d, ensure_ascii=False) + "\n")

out = ["Natures des décisions lues (d'après le titre) : " + " | ".join(f"{k}: {v}" for k, v in par_nature.most_common()),
       "Résultat : " + " | ".join(f"{k}: {v}" for k, v in compte.most_common()),
       f"Longueur du texte intégral (caractères) : médiane {sorted(longueurs)[len(longueurs) // 2] if longueurs else 0} "
       f"| minimum {min(longueurs, default=0)} | maximum {max(longueurs, default=0)}",
       "\n=== Motifs trouvés dans les décisions gardées ==="]
out += [f"   {k} : {v}" for k, v in par_motif.most_common()]
out.append(f"\nFichier créé : {sortie_chemin} ({sortie_chemin.stat().st_size / 1e6:.1f} Mo)")
texte = "\n".join(out)
Path("donnees", "controle_filtre_constit.txt").write_text(texte, encoding="utf-8")
print(texte)
print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\controle_filtre_constit.txt).")
