#!/usr/bin/env python3
"""
Téléchargement d'un code de Légifrance autre que le code des douanes (articles en vigueur).
Les fichiers du code des douanes ne sont jamais touchés : les sorties portent le nom du code demandé.

Utilisation (mêmes variables d'environnement PISTE que prototype_ingestion.py) :
   python code_generique.py cpp          # Code de procédure pénale
   python code_generique.py penal        # Code pénal
   python code_generique.py lpf          # Livre des procédures fiscales

Écrit :  donnees\\code_<nom>_table_matieres.json, donnees\\code_<nom>_articles.json, donnees\\controle_code_<nom>.txt
"""

import json
import sys
from collections import Counter
from datetime import date

import prototype_ingestion as pi

CODES = {
    "cpp": ("LEGITEXT000006071154", "procédure pénale"),
    "penal": ("LEGITEXT000006070719", "pénal"),
    "lpf": ("LEGITEXT000006069583", "procédures fiscales"),
}


def main():
    nom = sys.argv[1] if len(sys.argv) > 1 else ""
    if nom not in CODES:
        sys.exit(__doc__)
    text_id, mot = CODES[nom]
    aujourd_hui = date.today().isoformat()
    corps = {"textId": text_id, "date": aujourd_hui, "nature": "CODE"}
    rep = None
    for chemin in ("/consult/code/tableMatieres", "/consult/legi/tableMatieres"):
        rep = pi.appeler("POST", pi.LEGIFRANCE_BASE + chemin, json=corps)
        if rep.status_code == 200:
            break
    if rep is None or rep.status_code != 200:
        sys.exit(f"Table des matières inaccessible ({rep.status_code}) : {rep.text[:300]}")
    table = rep.json()
    titre = str(table.get("title") or table.get("titre") or "")
    print(f"Code reçu : {titre or '(titre absent)'}")
    if titre and mot.lower() not in titre.lower():
        sys.exit(f"Ce n'est pas le code attendu (« {mot} » absent du titre). Arrêt : rien n'est téléchargé.")
    pi.sauver(f"code_{nom}_table_matieres.json", table)

    articles = pi.lister_articles(table)
    en_vigueur = [a for a in articles if (a.get("etat") or "").upper().startswith("VIGUEUR")] or articles
    print(f"  {len(articles)} articles repérés, {len(en_vigueur)} à télécharger")

    textes, echecs = [], 0
    for i, art in enumerate(en_vigueur, 1):
        rep = pi.appeler("POST", pi.LEGIFRANCE_BASE + "/consult/getArticle", json={"id": art["id"]})
        if rep.status_code != 200:
            echecs += 1
            print(f"  échec {art['id']} ({rep.status_code})")
            continue
        d = rep.json().get("article", {})
        textes.append({"id": art["id"], "num": d.get("num") or art.get("num"), "chemin": art.get("chemin"),
                       "etat": d.get("etat"), "date_debut": pi.iso_date(d.get("dateDebut")),
                       "date_fin": pi.iso_date(d.get("dateFin")), "texte": d.get("texte") or d.get("texteHtml")})
        if i % 200 == 0:
            print(f"  {i}/{len(en_vigueur)}")
    pi.sauver(f"code_{nom}_articles.json", textes)

    vides = sum(1 for t in textes if not (t["texte"] or "").strip())
    out = [f"Code : {titre} ({text_id}) | état au {aujourd_hui}",
           f"Articles enregistrés : {len(textes)} | échecs : {echecs} | articles sans texte : {vides}",
           "États : " + " | ".join(f"{k}: {v}" for k, v in Counter(t["etat"] for t in textes).most_common()),
           "Exemples : " + " | ".join(f"art. {t['num']} ({(t['texte'] or '')[:60]!r})" for t in textes[:3])]
    for numero in ("429", "802", "63-1", "78-2", "61-1"):
        t = next((x for x in textes if str(x["num"]) == numero), None)
        if t:
            out.append(f"   art. {numero} : {(t['texte'] or '')[:160]!r}")
    texte = "\n".join(out)
    (pi.DOSSIER_SORTIE / f"controle_code_{nom}.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print(f"\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\controle_code_{nom}.txt).")


if __name__ == "__main__":
    main()
