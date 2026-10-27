#!/usr/bin/env python3
"""
Tri hors ligne de la jurisprudence administrative (JADE : Conseil d'État, cours administratives d'appel, tribunaux
administratifs) téléchargée par legifrance_jurisprudence.py. Aucun appel réseau, fichier d'origine intact.

Niveaux de pertinence douanière, lus dans le texte intégral (comme pour la Cour de cassation) :
  forte   = « code des douanes »
  moyenne = « administration des douanes » / « agents des douanes » / « direction générale des douanes »
  faible  = « douane » seulement (droits de douane, douanier...)
  aucune  = aucune mention : écartée

Utilisation :  python filtrer_cetat.py
Lit      :  donnees\\juri_cetat.jsonl
Écrit    :  donnees\\juri_cetat_douane.jsonl   (id, titre, juridiction, annee, publication, pertinence_douane,
                                               texte en clair, meta = autres champs de la décision)
            donnees\\controle_filtre_cetat.txt
"""

import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

source = Path("donnees") / "juri_cetat.jsonl"
if not source.exists():
    sys.exit(f"Fichier introuvable : {source}")
sortie_chemin = source.with_name("juri_cetat_douane.jsonl")


def chaines(o, chemin=()):
    if isinstance(o, str):
        yield chemin, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from chaines(v, chemin + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from chaines(v, chemin + (i,))


def retirer(o, chemin):
    """Copie de o dont la chaîne située à `chemin` est vidée (pour ne garder que les métadonnées)."""
    if not chemin:
        return ""
    k, reste = chemin[0], chemin[1:]
    if isinstance(o, dict):
        return {kk: (retirer(v, reste) if kk == k else v) for kk, v in o.items()}
    if isinstance(o, list):
        return [retirer(v, reste) if i == k else v for i, v in enumerate(o)]
    return o


def en_clair(brut):
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", brut)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def juridiction(titre):
    t = (titre or "").lower()
    if "conseil d'" in t and "tat" in t:
        return "Conseil d'État"
    if "cour administrative d'appel" in t or t.startswith("caa"):
        return "CAA"
    if "tribunal administratif" in t or t.startswith("ta "):
        return "TA"
    return "autre"


def publication(titre):
    t = (titre or "").lower()
    if "publié au recueil lebon" in t:
        return "Lebon"
    if "mentionné aux tables" in t:
        return "tables"
    if "inédit" in t:
        return "inédit"
    return "non indiquée"


FORTE = re.compile(r"code des douanes")
MOYENNE = re.compile(r"administration des douanes|agents? des douanes|direction g[ée]n[ée]rale des douanes|service des douanes")
FAIBLE = re.compile(r"douan")

compte, par_juri, par_pub, par_an = Counter(), Counter(), Counter(), Counter()
croise = Counter()
longueurs = []
with source.open(encoding="utf-8") as f, sortie_chemin.open("w", encoding="utf-8") as sortie:
    for ligne in f:
        if not ligne.strip():
            continue
        d = json.loads(ligne)
        decision = d.get("decision")
        candidates = list(chaines(decision))
        if not candidates:
            compte["sans texte"] += 1
            continue
        chemin, brut = max(candidates, key=lambda c: len(c[1]))
        texte = en_clair(brut)
        bas = texte.lower().replace("’", "'")
        niveau = ("forte" if FORTE.search(bas) else "moyenne" if MOYENNE.search(bas)
                  else "faible" if FAIBLE.search(bas) else "aucune")
        if niveau == "aucune":
            compte["écartées (aucune mention)"] += 1
            continue
        j, p = juridiction(d.get("titre")), publication(d.get("titre"))
        m = re.findall(r"\b(19\d{2}|20\d{2})\b", d.get("titre") or "")
        annee = m[0] if m else None
        compte["gardées " + niveau] += 1
        par_juri[j] += 1
        par_pub[p] += 1
        par_an[(annee or "????")[:3] + "0"] += 1
        croise[(j, niveau)] += 1
        longueurs.append(len(texte))
        sortie.write(json.dumps({"id": d["id"], "titre": d.get("titre"), "juridiction": j, "annee": annee,
                                 "publication": p, "pertinence_douane": niveau, "recherches": d.get("recherches"),
                                 "texte": texte, "meta": retirer(decision, chemin)}, ensure_ascii=False) + "\n")

out = ["Résultat : " + " | ".join(f"{k}: {v}" for k, v in compte.most_common()),
       "Par juridiction : " + " | ".join(f"{k}: {v}" for k, v in par_juri.most_common()),
       "Par niveau de publication : " + " | ".join(f"{k}: {v}" for k, v in par_pub.most_common()),
       "Par décennie : " + " | ".join(f"{k}: {v}" for k, v in sorted(par_an.items())),
       "Juridiction × pertinence : " + " | ".join(f"{j}/{n}: {v}" for (j, n), v in sorted(croise.items())),
       f"Longueur du texte (caractères) : médiane {sorted(longueurs)[len(longueurs) // 2] if longueurs else 0} "
       f"| minimum {min(longueurs, default=0)} | maximum {max(longueurs, default=0)}",
       f"\nFichier créé : {sortie_chemin} ({sortie_chemin.stat().st_size / 1e6:.0f} Mo)"]
texte = "\n".join(out)
Path("donnees", "controle_filtre_cetat.txt").write_text(texte, encoding="utf-8")
print(texte)
print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\controle_filtre_cetat.txt).")
