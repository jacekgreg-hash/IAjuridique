#!/usr/bin/env python3
"""
Test de pertinence de la recherche : pour chaque question de questions_reference.json, vérifie si les textes et décisions
attendus apparaissent dans les résultats, et à quel rang. À relancer après chaque modification du moteur de recherche
(recherche par le sens comprise) pour vérifier que rien ne s'est dégradé.

Utilisation :   python evaluer.py                    # utilise questions_reference.json
                python evaluer.py --k 20             # cherche dans les 20 premiers résultats de chaque famille
Écrit : controle_evaluation.txt
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import chercher


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default="questions_reference.json")
    ap.add_argument("--base", default=str(chercher.BASE_DEFAUT))
    ap.add_argument("--k", type=int, default=12, help="nombre de résultats examinés par famille (défaut 12)")
    a = ap.parse_args()
    if not Path(a.questions).exists() or not Path(a.base).exists():
        sys.exit("Fichier introuvable : " + (a.questions if not Path(a.questions).exists() else a.base))
    con = sqlite3.connect(a.base)
    questions = json.loads(Path(a.questions).read_text(encoding="utf-8"))["questions"]
    out, trouves_total, attendus_total = [], 0, 0
    par_origine = {}
    for q in questions:
        faits = q.get("faits")
        res = []
        for titre, liste in chercher.chercher_groupes(con, q["question"], a.k, n_par_famille=a.k, faits=faits):
            res += [(titre, i + 1, x["ref"]) for i, x in enumerate(liste)]
        for s in chercher.sections(con, q["question"], faits):
            res += [("Section : " + s["intitule"].split(">")[-1].strip(), i + 1, x["ref"]) for i, x in enumerate(s["articles"])]
        out.append(f"Question : {q['question']}  (faits : {faits or 'non précisé'})")
        if not q["attendus"]:
            out.append("   (aucun attendu renseigné : voici les premiers résultats, à valider ou corriger par un juriste)")
            for titre in dict.fromkeys(t for t, _, _ in res):
                out.append(f"   {titre} :")
                out += [f"      {rang}. {ref}" for t, rang, ref in res if t == titre and rang <= 6]
            out.append("")
            continue
        for att in q["attendus"]:
            attendus_total += 1
            ori = att.get("origine", "?")
            tot = par_origine.setdefault(ori, [0, 0])
            tot[1] += 1
            hit = next(((t, rang, ref) for t, rang, ref in res if att["ref"].lower() in ref.lower()), None)
            if hit:
                trouves_total += 1
                tot[0] += 1
                out.append(f"   OK    {att['ref']}  → {hit[0]}, rang {hit[1]}")
            else:
                out.append(f"   ABSENT {att['ref']}  (origine : {ori})")
        out.append("")
    out.append(f"Total : {trouves_total} attendus retrouvés sur {attendus_total}")
    for ori, (t, n) in sorted(par_origine.items()):
        out.append(f"   dont attendus d'origine « {ori} » : {t}/{n}")
    texte = "\n".join(out)
    Path("controle_evaluation.txt").write_text(texte, encoding="utf-8")
    print(texte)


if __name__ == "__main__":
    main()
