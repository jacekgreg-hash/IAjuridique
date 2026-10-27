#!/usr/bin/env python3
"""
Corrige les dates de la jurisprudence CJUE en les lisant dans l'en-tête du texte (hors réseau).

Utilisation :  python corriger_dates_cjue.py
Lit     :  donnees\\cjue\\cjue_douane.jsonl            (non modifié)
Écrit   :  donnees\\cjue\\cjue_douane_v2.jsonl         (champs ajoutés : date_decision, date_methode, alerte_texte_court)
           donnees\\cjue\\controle_dates.txt
"""

import json
import re
from collections import Counter
from pathlib import Path

D = Path("donnees") / "cjue"
MOIS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}
DATE = re.compile(r"\b(\d{1,2})(?:er)?\s+(" + "|".join(MOIS) + r")\s+(\d{4})\b", re.IGNORECASE)
REPERE = re.compile(r"(arr[êe]t|ordonnance|conclusions)[^\n]{0,200}?(?:du|le|présentées le)\s*$|"
                    r"(arr[êe]t|ordonnance)\s+de\s+la\s+cour[^\n]*|arr[êe]t\s+du\s+tribunal[^\n]*|"
                    r"conclusions\s+de\s+l.avocat[^\n]*|ordonnance\s+du\s+tribunal[^\n]*|"
                    r"ordonnance\s+de\s+la\s+cour[^\n]*", re.IGNORECASE)


def iso(m):
    return "%s-%02d-%02d" % (m.group(3), MOIS[m.group(2).lower()], int(m.group(1)))


ACTE = re.compile(r"(règlement|directive|décision|code|traité|convention|loi|arrêté|protocole|accord|"
                  r"acte|ordonnance n|déclaration)[^.\n]{0,90}$", re.IGNORECASE)
ENTETE = re.compile(r"^\s*(arr[êe]t|ordonnance|conclusions)\b", re.IGNORECASE)


def lire_date(texte, celex):
    """Renvoie (date ISO ou None, méthode)."""
    annee_affaire = int(celex[1:5])

    def vraisemblable(date):
        return annee_affaire <= int(date[:4]) <= annee_affaire + 15 and int(date[:4]) <= 2026

    # 1) ligne d'en-tête qui COMMENCE par Arrêt / Ordonnance / Conclusions (ou contient « présentées le »),
    #    date sur cette ligne ou sur l'une des deux suivantes
    lignes = texte[:20000].splitlines()
    for i, l in enumerate(lignes[:150]):
        if ENTETE.match(l) or "présentées le" in l:
            for cible in lignes[i:i + 3]:
                m = DATE.search(cible)
                if m and vraisemblable(iso(m)):
                    return iso(m), "en-tête"
    # 2) repli : première date plausible, hors dates d'actes juridiques cités
    refus = []
    for m in DATE.finditer(texte[:15000]):
        avant = texte[max(0, m.start() - 90):m.start()]
        if ACTE.search(avant):
            continue
        if vraisemblable(iso(m)):
            return iso(m), "première date plausible du texte"
        refus.append(iso(m))
    return None, ("dates écartées : " + ", ".join(refus[:3])) if refus else "aucune date trouvée"


def main():
    src = D / "cjue_douane.jsonl"
    decisions = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    methodes, par_annee, exemples, sans = Counter(), Counter(), [], []
    sortie = (D / "cjue_douane_v2.jsonl").open("w", encoding="utf-8")
    for d in decisions:
        date, methode = lire_date(d["texte"], d["celex"])
        d["date_sparql_non_fiable"] = d.pop("date", "")
        d["date_decision"] = date
        d["date_methode"] = methode
        d["alerte_texte_court"] = len(d["texte"]) < 6000
        methodes[methode.split(" :")[0].split(" (")[0]] += 1
        if date:
            par_annee[date[:4]] += 1
        else:
            sans.append((d["celex"], methode))
        if len(exemples) < 8 and d["celex"] in ("62002CJ0091", "62017CJ0236", "62010CJ0011", "61987CC0357", "61992CJ0377",
                                                  "61998CO0299") or (len(exemples) < 8 and len(decisions) and hash(d["celex"]) % 97 == 0):
            exemples.append((d["celex"], d["date_sparql_non_fiable"], date, methode, d["texte"][:0]))
        sortie.write(json.dumps(d, ensure_ascii=False) + "\n")
    sortie.close()

    out = [f"Décisions : {len(decisions)}", "", "=== Méthode de lecture de la date ==="]
    out += [f"   {k} : {v}" for k, v in methodes.items()]
    out += ["", "=== Exemples (celex | ancienne date non fiable → date lue | méthode) ==="]
    out += [f"   {c} | {a} → {b} | {m}" for c, a, b, m, _ in exemples]
    out += ["", f"=== Sans date fiable : {len(sans)} ==="]
    debuts = {d["celex"]: d["texte"] for d in decisions}
    for c, m in sans[:25]:
        out.append(f"   {c} : {m}")
        out.append(f"        début : {debuts[c][:260]!r}")
    out += ["", "=== Décisions par année (date lue dans le texte) ==="]
    out.append("   " + " | ".join(f"{a}: {n}" for a, n in sorted(par_annee.items())))
    texte = "\n".join(out)
    (D / "controle_dates.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\cjue\\controle_dates.txt).")


if __name__ == "__main__":
    main()
