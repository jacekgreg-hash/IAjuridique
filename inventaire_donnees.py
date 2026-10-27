#!/usr/bin/env python3
"""
Inventaire des fichiers de données (aucun appel réseau, rien n'est modifié) : pour chaque fichier .json / .jsonl,
sa taille, le nombre d'enregistrements et la structure du premier enregistrement (noms des champs, types, longueur des
textes). Sert à écrire correctement la construction de l'index de recherche.

Utilisation :   python inventaire_donnees.py
Écrit    :  donnees\\inventaire_donnees.txt
"""

import json
from pathlib import Path

RACINE = Path("donnees")
IGNORER = {"fichiers", "da_html", "pages", "textes"}   # dossiers de pièces brutes (PDF, HTML, un .txt par DA)
LIMITE_JSON = 400e6


def decrire(o, profondeur=0, nom=""):
    """Description compacte d'un objet JSON : types, longueurs de chaînes, premiers éléments de listes."""
    marge = "    " * profondeur
    if isinstance(o, dict):
        lignes = []
        for k, v in list(o.items())[:40]:
            if isinstance(v, (dict, list)) and profondeur < 2:
                lignes.append(f"{marge}{k} : {type(v).__name__}({len(v)})")
                lignes += decrire(v, profondeur + 1, k)
            else:
                lignes.append(f"{marge}{k} : {resume(v)}")
        return lignes
    if isinstance(o, list) and o:
        return [f"{marge}[0] :"] + (decrire(o[0], profondeur + 1) if isinstance(o[0], (dict, list)) and profondeur < 2
                                    else [f"{marge}    {resume(o[0])}"])
    return []


def resume(v):
    if isinstance(v, str):
        return f"str({len(v)}) {v[:70]!r}"
    if isinstance(v, (dict, list)):
        return f"{type(v).__name__}({len(v)})"
    return f"{type(v).__name__} {v!r}"[:90]


def main():
    sortie = []
    fichiers = sorted(p for p in RACINE.rglob("*") if p.is_file() and p.suffix in (".json", ".jsonl")
                      and not (set(p.relative_to(RACINE).parts[:-1]) & IGNORER))
    for p in fichiers:
        taille = p.stat().st_size
        en_tete = f"\n##### {p.relative_to(RACINE)} ({taille / 1e6:.1f} Mo)"
        sortie.append(en_tete)
        try:
            if p.suffix == ".jsonl":
                n, premier = 0, None
                with p.open(encoding="utf-8") as f:
                    for ligne in f:
                        if ligne.strip():
                            n += 1
                            if premier is None:
                                premier = json.loads(ligne)
                sortie.append(f"  jsonl : {n} enregistrements")
                if premier is not None:
                    sortie += ["  " + l for l in decrire(premier)]
            elif taille > LIMITE_JSON:
                sortie.append("  trop gros pour être lu en entier, ignoré")
            else:
                j = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(j, list):
                    sortie.append(f"  liste de {len(j)} éléments")
                    sortie += ["  " + l for l in (decrire(j[0]) if j else [])]
                elif isinstance(j, dict):
                    sortie.append(f"  objet à {len(j)} clés : {list(j)[:12]}")
                    sortie += ["  " + l for l in decrire(j)]
        except Exception as e:
            sortie.append(f"  illisible : {str(e)[:100]}")
    texte = "\n".join(sortie)
    (RACINE / "inventaire_donnees.txt").write_text(texte, encoding="utf-8")
    print(f"{len(fichiers)} fichiers décrits. Résultat : donnees\\inventaire_donnees.txt")
    print("\nEnvoyez-moi ce fichier (donnees\\inventaire_donnees.txt).")


if __name__ == "__main__":
    main()
