#!/usr/bin/env python3
"""
Construction du corpus « doctrine » : un enregistrement par décision administrative (DA), prêt pour l'indexation.

 - les fichiers regroupant plusieurs textes (un fichier par BOD) sont découpés à chaque page de couverture
   « BOD n° ... du ... / texte n° XX-NNN / nature du texte : ... » ; les simples renvois « texte n° 93-182 » ne coupent pas ;
 - les fichiers identiques partagés par plusieurs DA ne sont traités qu'une fois ;
 - les métadonnées (titre, dates, classement, BOD, abrogation, relations) viennent des pages du BOD (da_detail.json) ;
 - les décisions sans contenu (étiquette « Abrogé par BOD ... » ou titre seul) sont conservées, marquées sans_contenu.

Utilisation :   python da_corpus.py
Lit      :  donnees\\bod\\da_detail.json, textes_manifest.json, textes\\*.txt
Écrit    :  donnees\\bod\\corpus_doctrine.jsonl, donnees\\bod\\controle_corpus.txt
"""

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

DOSSIER = Path("donnees") / "bod"
TEXTES = DOSSIER / "textes"
COUVERTURE = re.compile(r"\btexte\s*n\s*[°ºo]\s*:?\s*(\d{2}-\d{3})\s*(?:\n\s*)*nature\s+du\s+texte", re.IGNORECASE)
RECUL_BOD = 160   # la page de couverture commence par « BOD n° ... du ... » juste avant
SOMMAIRE_MAX = 1500


def lire(ident):
    p = TEXTES / f"{ident}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def normaliser(t):
    return re.sub(r"\s+", " ", t).strip()


def decouper(texte):
    """Renvoie [(numéro DA, texte du segment)] et la taille du sommaire écarté ; liste vide si aucune couverture."""
    ms = list(COUVERTURE.finditer(texte))
    if not ms:
        return [], 0
    debuts = []
    for m in ms:
        avant = texte[max(0, m.start() - RECUL_BOD): m.start()]
        k = avant.rfind("BOD")
        debuts.append(m.start() - (len(avant) - k) if k >= 0 else m.start())
    ecarte = 0
    if debuts[0] > 0:
        if len(ms) == 1 and debuts[0] < SOMMAIRE_MAX:
            debuts[0] = 0          # un seul texte : on garde l'en-tête du fichier
        else:
            ecarte = debuts[0]     # sommaire du BOD (liste des textes), non conservé
    segments = []
    for i, m in enumerate(ms):
        fin = debuts[i + 1] if i + 1 < len(ms) else len(texte)
        segments.append((m.group(1), texte[debuts[i]:fin].strip()))
    return segments, ecarte


def main():
    detail = {d["id"]: d for d in json.loads((DOSSIER / "da_detail.json").read_text(encoding="utf-8"))}
    manifeste = {r["id"]: r for r in json.loads((DOSSIER / "textes_manifest.json").read_text(encoding="utf-8"))}

    # 1. regrouper les fichiers identiques
    groupes = defaultdict(list)
    for ident, r in manifeste.items():
        if r["statut"] in ("ok", "ok_ocr"):
            groupes[hashlib.md5(normaliser(lire(ident)).encode()).hexdigest()].append(ident)

    # 2. découper chaque texte distinct
    docs, stats = {}, Counter()
    ecartes = 0
    for membres in groupes.values():
        membres = sorted(membres)
        texte = lire(membres[0])
        segments, ecarte = decouper(texte)
        ecartes += ecarte
        if segments:
            stats["fichiers découpés" if len(segments) > 1 else "fichiers à une couverture"] += 1
            for numero, seg in segments:
                if numero in docs and normaliser(docs[numero]["texte"]) != normaliser(seg):
                    docs[numero]["texte"] += "\n\n" + seg      # même DA présente dans deux fichiers différents
                    stats["DA présente dans plusieurs fichiers"] += 1
                elif numero not in docs:
                    docs[numero] = {"texte": seg, "source": membres[0], "decoupage": "couverture",
                                    "partage": membres if len(membres) > 1 else []}
        else:
            stats["fichiers sans couverture (entiers)"] += 1
            docs[membres[0]] = {"texte": texte, "source": membres[0], "decoupage": "fichier entier",
                                "partage": membres[1:] if len(membres) > 1 else []}
            for autre in membres[1:]:
                docs.setdefault(autre, {"texte": "", "source": membres[0], "decoupage": "renvoi", "partage": []})

    # 3. un enregistrement par DA connue
    tous = sorted(set(detail) | set(docs) | set(manifeste))
    ecriture, c = [], Counter()
    non_localises = []
    for ident in tous:
        d, r, doc = detail.get(ident, {}), manifeste.get(ident, {}), docs.get(ident)
        stub = r.get("statut") in ("court", "ocr_faible")
        if doc is None and r.get("statut") in ("ok", "ok_ocr"):
            non_localises.append(ident)        # fichier lu mais cette DA n'y a pas de page de couverture
        texte = doc["texte"] if doc else (lire(ident) if stub else "")
        sans_contenu = stub or not texte.strip()
        abrogee = bool(d.get("abrogee_par")) or bool(re.search(r"abrogé|abrogée", texte[:400], re.IGNORECASE) and stub)
        rec = {
            "id": ident, "titre": d.get("titre"), "date_publication": d.get("date_publication") or r.get("date_publication"),
            "date_entree_en_vigueur": d.get("date_entree_en_vigueur"), "classement": d.get("classement") or r.get("classement"),
            "bureau": d.get("bureau"), "bod": d.get("bod"), "abrogee": abrogee, "abrogee_par": d.get("abrogee_par", []),
            "relations": d.get("relations", []), "sans_contenu": sans_contenu,
            "extraction": r.get("methode"), "statut_extraction": r.get("statut"),
            "decoupage": doc["decoupage"] if doc else ("etiquette" if stub else "aucun"),
            "fichier_source": doc["source"] if doc else None, "partage_avec": doc["partage"] if doc else [],
            "caracteres": len(texte), "texte": texte,
        }
        ecriture.append(rec)
        c["avec contenu" if not sans_contenu else "sans contenu"] += 1
        c["abrogées"] += abrogee
    with open(DOSSIER / "corpus_doctrine.jsonl", "w", encoding="utf-8") as f:
        for rec in ecriture:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    avec = [r for r in ecriture if not r["sans_contenu"]]
    tailles = sorted(r["caracteres"] for r in avec)
    out = [f"Enregistrements (DA) : {len(ecriture)} | avec contenu : {c['avec contenu']} | sans contenu : {c['sans contenu']} "
           f"| marquées abrogées : {c['abrogées']}",
           f"Fichiers distincts : {len(groupes)} | " + " | ".join(f"{k}: {v}" for k, v in stats.items()),
           f"Sommaires de BOD écartés : {ecartes:,} caractères".replace(",", " "),
           "Découpage : " + " | ".join(f"{k}: {v}" for k, v in Counter(r['decoupage'] for r in ecriture).most_common()),
           f"DA dont le fichier a été lu mais sans page de couverture propre : {len(non_localises)} {non_localises[:12]}"]
    if tailles:
        q = lambda p: tailles[min(len(tailles) - 1, int(len(tailles) * p))]
        out.append(f"Taille d'un texte (caractères) : médiane {q(0.5):,} | 90e centile {q(0.9):,} | 99e {q(0.99):,} | max {tailles[-1]:,}".replace(",", " "))
        out.append(f"Total caractères indexables : {sum(tailles):,}".replace(",", " "))
    par_an = Counter(((r['date_publication'] or '????')[:3] + '0', r['sans_contenu']) for r in ecriture)
    out.append("Par décennie (avec contenu / sans) : " + " | ".join(
        f"{d}: {par_an[(d, False)]}/{par_an[(d, True)]}" for d in sorted({k[0] for k in par_an})))
    out.append("\n=== Vérification : fichiers découpés ===")
    for ident in ("98-199", "97-130", "01-041", "99-057", "01-117", "01-139"):
        r = next((x for x in ecriture if x["id"] == ident), None)
        if r:
            out.append(f"--- DA {ident} | {str(r['titre'])[:70]} | {r['decoupage']} | {r['caracteres']} car. | sans_contenu={r['sans_contenu']}"
                       f"\n    début : {re.sub(chr(10), ' ⏎ ', r['texte'][:230])!r}")
    texte = "\n".join(out)
    (DOSSIER / "controle_corpus.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\bod\\controle_corpus.txt).")


if __name__ == "__main__":
    main()
