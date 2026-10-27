#!/usr/bin/env python3
"""
Tri hors ligne de la jurisprudence « générale » téléchargée (aucun appel réseau, fichier d'origine intact).

La recherche de Judilibre ne tient pas compte des expressions exactes (constaté : « article 324 du code des douanes »
renvoyait presque toutes les décisions). Le tri se fait donc ici, sur le texte intégral, avec des expressions précises.

Utilisation :  python filtrer_jurisprudence_generale.py [FICHIER.jsonl]
Par défaut :   donnees\\jurisprudence_generale.jsonl
Résultat :     donnees\\jurisprudence_generale_filtree.jsonl   (champs ajoutés : themes_generaux, motifs, pertinence_douane)
               donnees\\controle_filtre_generale.txt
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("donnees") / "jurisprudence_generale.jsonl"
if not source.exists():
    sys.exit(f"Fichier introuvable : {source}")
sortie_chemin = source.with_name(source.stem + "_filtree.jsonl")

# (thème, étiquette, expression régulière appliquée au texte en minuscules, apostrophes droites)
MOTIFS = [
    ("nullité des procès-verbaux", "nullité du procès-verbal", r"nullit[ée]s? (?:du|des|de ce|de ces|d'un|d'une)? ?proc[èe]s-verba(?:l|ux)"),
    ("nullité des procès-verbaux", "foi des procès-verbaux", r"foi due aux proc[èe]s-verbaux|proc[èe]s-verba(?:l|ux)[^.]{0,200}\bfont? foi"),
    ("nullité des procès-verbaux", "inscription de faux", r"inscription de faux"),
    ("nullité des procès-verbaux", "article 802 CPP / nullité substantielle", r"\b802 du code de proc[ée]dure p[ée]nale|nullit[ée] substantielle"),
    ("nullité des procès-verbaux", "article 429 CPP", r"\b429 du code de proc[ée]dure p[ée]nale"),
    ("droits de la défense", "droits de la défense", r"droits? de la d[ée]fense"),
    ("droits de la défense", "droit de se taire", r"droit de se taire|garder le silence|droit au silence"),
    ("droits de la défense", "assistance d'un avocat", r"assistance d'un avocat|assist[ée]e? (?:par|d'un) (?:un )?avocat"),
    ("droits de la défense", "notification des droits", r"notification (?:de ses|des) droits|notifi[ée]s? (?:de ses|des) droits"),
    ("droits de la défense", "égalité des armes / contradictoire", r"[ée]galit[ée] des armes|principe (?:du contradictoire|de la contradiction)"),
    ("droits de la défense", "article 6 CEDH / procès équitable", r"article 6[^.]{0,60}convention europ[ée]enne|proc[èe]s [ée]quitable"),
    ("procédure et preuve", "loyauté de la preuve", r"loyaut[ée] de la preuve"),
    ("procédure et preuve", "visite domiciliaire / art. 64", r"visites? domiciliaires?|\b64 du code des douanes"),
    ("procédure et preuve", "articles 63, 323, 324, 334 code des douanes",
     r"articles? (?:63|323|324|334)(?: [a-z-]+)? (?:du|dudit) code des douanes|articles? 323 et 324|articles? 323, 324"),
    ("procédure et preuve", "ne bis in idem", r"ne bis in idem"),
    ("procédure et preuve", "prescription de l'action publique", r"prescription de l'action publique"),
]
# Motifs « larges » : très fréquents dans toute la jurisprudence, ils ne suffisent pas seuls hors chambre criminelle
LARGES = {"droits de la défense", "égalité des armes / contradictoire", "article 6 CEDH / procès équitable",
          "prescription de l'action publique"}
COMPILES = [(t, e, re.compile(p)) for t, e, p in MOTIFS]


def normaliser(t):
    return (t or "").lower().replace("’", "'").replace("\xa0", " ").replace(" ", " ")


compte_motif, compte_theme, par_chambre, par_annee, niveaux = Counter(), Counter(), Counter(), Counter(), Counter()
total = gardees = 0
with source.open(encoding="utf-8") as f, sortie_chemin.open("w", encoding="utf-8") as sortie:
    for ligne in f:
        if not ligne.strip():
            continue
        try:
            d = json.loads(ligne)
        except ValueError:
            continue
        total += 1
        texte = normaliser(d.get("text"))
        motifs = [(t, e) for t, e, rx in COMPILES if rx.search(texte)]
        if not motifs:
            continue
        penal = d.get("chamber") in ("cr", "pl", "mi")
        douane = "code des douanes" in texte or "administration des douanes" in texte
        precis = any(e not in LARGES for _, e in motifs)
        # Règle de tri : en chambre criminelle / mixte / plénière, tout motif retenu compte (niveau A si motif précis,
        # B si motif large seul) ; en chambre commerciale, il faut en plus une mention de la douane.
        if not (penal or douane):
            continue
        d["niveau_general"] = "A" if precis else "B"
        gardees += 1
        niveaux[d["niveau_general"]] += 1
        d["themes_generaux"] = sorted({t for t, _ in motifs})
        d["motifs"] = [e for _, e in motifs]
        d["pertinence_douane"] = ("forte" if "code des douanes" in texte else
                                  "moyenne" if "administration des douanes" in texte else
                                  "faible" if "douan" in texte else "aucune")
        for _, e in motifs:
            compte_motif[e] += 1
        for t in d["themes_generaux"]:
            compte_theme[t] += 1
        par_chambre[str(d.get("chamber"))] += 1
        par_annee[str(d.get("decision_date") or "????")[:3] + "0"] += 1
        sortie.write(json.dumps(d, ensure_ascii=False) + "\n")

out = [f"Décisions lues : {total} | gardées : {gardees} | écartées : {total - gardees}",
       "Niveaux : " + " | ".join(f"{k}: {v}" for k, v in sorted(niveaux.items())) + "   (A = motif précis, B = motif large seul)",
       "Par thème : " + " | ".join(f"{k}: {v}" for k, v in compte_theme.most_common()),
       "Par chambre : " + " | ".join(f"{k}: {v}" for k, v in par_chambre.most_common()),
       "Par décennie : " + " | ".join(f"{k}: {v}" for k, v in sorted(par_annee.items())),
       "\n=== Décisions gardées par motif (une décision peut compter dans plusieurs) ==="]
out += [f"   {k} : {v}" for k, v in compte_motif.most_common()]
out.append(f"\nFichier créé : {sortie_chemin} ({sortie_chemin.stat().st_size / 1e6:.0f} Mo)")
texte = "\n".join(out)
source.with_name("controle_filtre_generale.txt").write_text(texte, encoding="utf-8")
print(texte)
print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\controle_filtre_generale.txt).")
