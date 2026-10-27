#!/usr/bin/env python3
"""Contrôle de la jurisprudence CJUE téléchargée (hors réseau).
Utilisation :  python controle_cjue.py
Résultat aussi enregistré dans donnees\\cjue\\controle_cjue.txt"""

import json
from collections import Counter
from pathlib import Path

D = Path("donnees") / "cjue"
decisions = [json.loads(l) for l in (D / "cjue_douane.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
echecs = json.loads((D / "echecs.json").read_text(encoding="utf-8")) if (D / "echecs.json").exists() else []
liste = {x["celex"]: x for x in json.loads((D / "liste.json").read_text(encoding="utf-8"))}

out = [f"Décisions téléchargées : {len(decisions)} | échecs : {len(echecs)}"]
out.append("\n=== Échecs (celex | type | date | pertinence | détail) ===")
for e in echecs:
    m = liste.get(e["celex"], {})
    out.append(f"   {e['celex']} | {m.get('type', '?')} | {m.get('date', '?')} | {m.get('pertinence', '?')} | {e['détail'][:90]}")

out.append("\n=== Par type et pertinence ===")
for (t, p), n in sorted(Counter((d["type"], d["pertinence"]) for d in decisions).items()):
    out.append(f"   {t} / {p} : {n}")

longueurs = [len(d["texte"]) for d in decisions]
longueurs.sort()
out.append("\n=== Longueur des textes (caractères) ===")
out.append(f"   min {longueurs[0]} | médiane {longueurs[len(longueurs) // 2]} | max {longueurs[-1]}")
courts = [d for d in decisions if len(d["texte"]) < 6000]
out.append(f"   textes de moins de 6000 caractères : {len(courts)}")
for d in courts[:6]:
    out.append(f"      {d['celex']} ({d['type']}, {d['date']}) {len(d['texte'])} car. : {d['texte'][:140]!r}")

mots = Counter()
for d in decisions:
    t = d["texte"].lower()
    mots["mentionne « douan… »"] += "douan" in t
    mots["contient « la cour » ou « le tribunal »"] += ("la cour" in t or "le tribunal" in t)
    mots["contient « dispositif » ou « par ces motifs »"] += ("par ces motifs" in t or "dispositif" in t)
    mots["écrit en français (« les », « des », « de la »)"] += (" des " in t and " les " in t)
    mots["semble non français (« the », « der », « die »)"] += (" the " in t and " of " in t) or (" der " in t and " die " in t)
out.append("\n=== Contenu ===")
for k, v in mots.items():
    out.append(f"   {k} : {v} / {len(decisions)}")

par_annee = Counter(d["date"][:4] for d in decisions)
out.append("\n=== Par année ===")
out.append("   " + " | ".join(f"{a}: {n}" for a, n in sorted(par_annee.items())))

out.append("\n=== Exemples (début du texte) ===")
for d in decisions[:: max(1, len(decisions) // 4)][:4]:
    out.append(f"   {d['celex']} ({d['type']}, {d['date']}, {d['pertinence']}) : {d['texte'][:200]!r}")

texte = "\n".join(out)
(D / "controle_cjue.txt").write_text(texte, encoding="utf-8")
print(texte)
print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\cjue\\controle_cjue.txt).")
