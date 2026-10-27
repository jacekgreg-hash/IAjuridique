#!/usr/bin/env python3
"""
Contrôle des fichiers du code des douanes déjà téléchargés (aucun appel réseau).

Utilisation :
  python controle_codes.py            # lit le dossier ./donnees
  python controle_codes.py AUTRE_DOSSIER

Il vérifie :
  - le nombre d'articles par famille (L, R, A) dans le nouveau code ;
  - la présence de quelques articles de l'ancien code souvent cités par la jurisprudence ;
  - l'existence d'une table de concordance ancien/nouveau dans la structure du code.
"""

import json
import sys
from pathlib import Path

dossier = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("donnees")


def charger(nom):
    chemin = dossier / nom
    if not chemin.exists():
        print(f"Fichier absent : {chemin}")
        return None
    return json.loads(chemin.read_text(encoding="utf-8"))


def apercu(texte, n=220):
    texte = (texte or "").replace("\n", " ").strip()
    return texte[:n] + ("…" if len(texte) > n else "")


def chercher_noeuds(noeud, mot, trouves, profondeur=0):
    """Cherche récursivement des noeuds dont le titre contient `mot`."""
    if isinstance(noeud, dict):
        titre = str(noeud.get("title") or noeud.get("titre") or "")
        if mot in titre.lower():
            trouves.append({
                "titre": titre,
                "id": noeud.get("id") or noeud.get("cid"),
                "etat": noeud.get("etat"),
                "nb_articles": len(noeud.get("articles") or []),
                "nb_sections": len(noeud.get("sections") or []),
            })
        for valeur in noeud.values():
            chercher_noeuds(valeur, mot, trouves, profondeur + 1)
    elif isinstance(noeud, list):
        for element in noeud:
            chercher_noeuds(element, mot, trouves, profondeur + 1)


# ---------------------------------------------------------------------------
print("=== NOUVEAU CODE ===")
nouveau = charger("code_douanes_nouveau_articles.json")
if nouveau:
    familles = {"L": 0, "R": 0, "A": 0, "autres": 0}
    livres = {}
    autres = {}
    for art in nouveau:
        num = str(art.get("num") or "")
        premiere = num[:1].upper()
        familles[premiere if premiere in ("L", "R", "A") else "autres"] += 1
        segments = [x.strip() for x in (art.get("chemin") or "").split(">")]
        racine = segments[1] if len(segments) > 1 else (segments[0] or "(sans chemin)")
        livres[racine] = livres.get(racine, 0) + 1
        if premiere not in ("L", "R", "A"):
            prefixe = num[:2] or "(vide)"
            autres.setdefault(prefixe, []).append(num)
    print(f"Articles téléchargés : {len(nouveau)}")
    print(f"Par famille : {familles}  (annonce, source secondaire : L 890, R 528, A 91)")
    print("Par grande division :")
    for nom, nb in sorted(livres.items(), key=lambda x: -x[1])[:12]:
        print(f"   {nb:5d}  {nom[:90]}")
    if autres:
        print("Articles à autre préfixe (début de numéro : nombre ; exemples) :")
        for pref, nums in sorted(autres.items(), key=lambda x: -len(x[1]))[:10]:
            print(f"   {pref!r} : {len(nums)} ; {', '.join(nums[:4])}")
    premier = nouveau[0]
    print(f"Premier article : {premier.get('num')} | en vigueur depuis {premier.get('date_debut')}")
    print(f"   {apercu(premier.get('texte'))}")

# ---------------------------------------------------------------------------
print("\n=== ANCIEN CODE (au 30 avril 2026) ===")
ancien = charger("code_douanes_ancien_articles.json")
if ancien:
    par_num = {}
    for art in ancien:
        par_num.setdefault(str(art.get("num")).strip(), art)
    print(f"Articles téléchargés : {len(ancien)}")
    for num in ("60", "63 ter", "64", "354", "369", "370", "414"):
        art = par_num.get(num)
        if art:
            print(f"  art. {num} : présent | {apercu(art.get('texte'), 130)}")
        else:
            print(f"  art. {num} : ABSENT du fichier")

# ---------------------------------------------------------------------------
print("\n=== TABLE DE CONCORDANCE ===")
for nom in ("code_douanes_nouveau_table_matieres.json", "code_douanes_ancien_table_matieres.json"):
    table = charger(nom)
    if table is None:
        continue
    trouves = []
    chercher_noeuds(table, "concordance", trouves)
    print(f"{nom} : {len(trouves)} noeud(s) contenant « concordance » dans le titre")
    for t in trouves[:15]:
        print(f"   {t}")

if nouveau:
    articles_concordance = [
        a for a in nouveau
        if "concordance" in (a.get("chemin") or "").lower()
        or "concordance" in str(a.get("num") or "").lower()
    ]
    print(f"Articles téléchargés rattachés à une section « concordance » : {len(articles_concordance)}")
    for a in articles_concordance[:5]:
        print(f"   {a.get('num')} | {a.get('chemin')} | {apercu(a.get('texte'), 100)}")

print("\nCopiez-collez ce résultat à Claude.")
