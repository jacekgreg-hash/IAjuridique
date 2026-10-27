#!/usr/bin/env python3
"""
Concordance code des douanes de l'Union : règlement 952/2013 (ancien) -> règlement 2026/2108 (nouveau).
Source : tableau de correspondance en annexe du règlement 2026/2108 (hors réseau).

Utilisation :  python importer_concordance_ue.py
Lit     :  donnees\\eurlex\\32026R2108.json
Écrit   :  donnees\\eurlex\\concordance_ue.json
"""

import json
import re
from collections import defaultdict
from pathlib import Path

DOSSIER = Path("donnees") / "eurlex"
d = json.loads((DOSSIER / "32026R2108.json").read_text(encoding="utf-8"))
lignes = d.get("annexes", "").splitlines()

debut = next(i for i, l in enumerate(lignes) if "TABLEAU DE CORRESPONDANCE" in l.upper())
corps = lignes[debut + 1:]
# en-tête : deux lignes (« Règlement (UE) no 952/2013 », « Le présent règlement »)
assert corps[0].startswith("Règlement (UE) no 952/2013") and corps[1].startswith("Le présent règlement"), corps[:3]
corps = corps[2:]
fin = next((i for i, l in enumerate(corps) if l.startswith(("ELI:", "ISSN"))), len(corps))
corps = corps[:fin]


def numeros(cellule):
    """Numéros d'articles cités dans une cellule (« Article 1er, paragraphe 3 », « Articles 74 et 75 »...)."""
    nums = set()
    for m in re.finditer(r"[Aa]rticles?\s+(\d+)(?:er)?(?:\s*(à|et)\s*(\d+))?", cellule):
        a = int(m.group(1))
        nums.add(a)
        if m.group(2) and m.group(3):
            b = int(m.group(3))
            if m.group(2) == "à" and b > a and b - a < 60:
                nums.update(range(a, b + 1))
            else:
                nums.add(b)
    return sorted(nums)


print(f"Lignes du tableau : {len(corps)}")
if len(corps) % 2:
    print("ATTENTION : nombre impair de lignes, l'alignement des colonnes est douteux.")

lignes_tableau, titres = [], []
for i in range(0, len(corps) - 1, 2):
    a, n = corps[i].strip(), corps[i + 1].strip()
    if a.startswith("Titre") and n.startswith("Titre"):
        titres.append({"ancien": a, "nouveau": n})
        continue
    lignes_tableau.append((a, n))

# Contrôle d'alignement : la colonne de gauche (ancien code) doit suivre l'ordre des articles.
precedent, retours = 0, []
for k, (a, n) in enumerate(lignes_tableau):
    nums = numeros(a)
    if nums:
        if nums[0] < precedent - 0:
            retours.append((k, precedent, nums[0], a[:60]))
        precedent = max(precedent, nums[0])
print(f"Lignes de correspondance : {len(lignes_tableau)} | titres : {len(titres)}")
print(f"Retours en arrière dans la colonne de gauche (devrait être 0) : {len(retours)}", retours[:5])

ancien_vers_nouveau = defaultdict(list)
nouveau_vers_ancien = defaultdict(list)
sans_equivalent_lignes = 0
for a, n in lignes_tableau:
    olds = numeros(a)
    if n in ("—", "-", ""):
        sans_equivalent_lignes += 1
        for o in olds:
            ancien_vers_nouveau[o].append({"nouveau": None, "ancien_ref": a, "nouveau_ref": n})
        continue
    news = numeros(n)
    for o in olds:
        ancien_vers_nouveau[o].append({"nouveau": news, "ancien_ref": a, "nouveau_ref": n})
    for x in news:
        nouveau_vers_ancien[x].append({"ancien": olds, "ancien_ref": a, "nouveau_ref": n})

anciens = {}
for o in range(1, 289):
    lst = ancien_vers_nouveau.get(o)
    if not lst:
        anciens[o] = {"statut": "absent du tableau", "correspondances": []}
    elif all(c["nouveau"] is None for c in lst):
        anciens[o] = {"statut": "sans équivalent (« — »)", "correspondances": lst}
    else:
        anciens[o] = {"statut": "repris", "correspondances": [c for c in lst if c["nouveau"] is not None],
                      "sans_equivalent_pour_partie": any(c["nouveau"] is None for c in lst)}

nouveaux = {n: {"statut": "issu de l'ancien code" if nouveau_vers_ancien.get(n) else "sans ancien équivalent dans le tableau",
                "correspondances": nouveau_vers_ancien.get(n, [])} for n in range(1, 288)}

sortie = {
    "source": "Tableau de correspondance, annexe du règlement (UE) 2026/2108 (colonne gauche : règlement (UE) n° 952/2013 ; colonne droite : le présent règlement)",
    "avertissement": ("Le tableau est la table officielle de lecture des renvois (art. 284 par. 1). Le règlement 952/2013 reste "
                      "applicable jusqu'à l'application du nouveau règlement (21 septembre 2027, sous réserve des dispositions "
                      "applicables plus tôt ou plus tard : art. 287)."),
    "ancien_vers_nouveau": anciens, "nouveau_vers_ancien": nouveaux, "titres": titres,
}
(DOSSIER / "concordance_ue.json").write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")

stat = defaultdict(list)
for o, v in anciens.items():
    stat[v["statut"]].append(o)
print("\n=== ANCIEN CODE (952/2013, articles 1 à 288) ===")
for s, l in stat.items():
    print(f"   {s} : {len(l)}" + (f"  -> {l[:40]}" if s != "repris" else ""))
sans_ancien = [n for n, v in nouveaux.items() if not v["correspondances"]]
print("\n=== NOUVEAU CODE (2026/2108, articles 1 à 287) ===")
print(f"   issus de l'ancien code : {287 - len(sans_ancien)} | sans ancien équivalent dans le tableau : {len(sans_ancien)}")
print(f"   {sans_ancien[:60]}")
print(f"\nLignes avec « — » côté nouveau : {sans_equivalent_lignes}")
print("Fichier créé :", DOSSIER / "concordance_ue.json")
print("\nCopiez-collez ce résultat à Claude.")
