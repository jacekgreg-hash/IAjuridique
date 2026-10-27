#!/usr/bin/env python3
"""
Construction de l'index de recherche (SQLite + FTS5, aucune installation supplémentaire) à partir des passages.

Utilisation :   python index_passages.py
Lit      :  donnees\\index\\passages.jsonl
Écrit    :  donnees\\index\\corpus.db   (base de recherche, quelques centaines de Mo)
            donnees\\index\\controle_index.txt
Relançable : l'ancienne base est remplacée.
"""

import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

DONNEES = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("donnees")
SOURCE = DONNEES / "index" / "passages.jsonl"
BASE = DONNEES / "index" / "corpus.db"


def main():
    if not SOURCE.exists():
        sys.exit(f"Fichier introuvable : {SOURCE} (lancez d'abord construire_passages.py)")
    if BASE.exists():
        BASE.unlink()
    con = sqlite3.connect(BASE)
    try:
        con.execute("CREATE VIRTUAL TABLE _essai USING fts5(x)")
        con.execute("DROP TABLE _essai")
    except sqlite3.OperationalError:
        sys.exit("Cette installation de Python n'a pas le module de recherche FTS5 de SQLite. Dites-le à Claude.")
    con.executescript("""
        PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
        CREATE TABLE passages (
            id INTEGER PRIMARY KEY, pid TEXT UNIQUE, source TEXT, famille TEXT, doc_id TEXT, ref TEXT, titre TEXT,
            section TEXT, date TEXT, statut TEXT, statut_detail TEXT, poids REAL, texte TEXT, meta TEXT);
    """)
    t0, n = time.time(), 0
    lot = []
    with SOURCE.open(encoding="utf-8") as f:
        for ligne in f:
            if not ligne.strip():
                continue
            p = json.loads(ligne)
            lot.append((p["pid"], p["source"], p["famille"], p["doc_id"], p["ref"], p.get("titre"), p.get("section"),
                        p.get("date"), p["statut"], p.get("statut_detail"), p["poids"], p["texte"],
                        json.dumps(p.get("meta") or {}, ensure_ascii=False)))
            n += 1
            if len(lot) >= 5000:
                con.executemany("INSERT INTO passages (pid, source, famille, doc_id, ref, titre, section, date, statut, "
                                "statut_detail, poids, texte, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", lot)
                lot = []
                print(f"  {n} passages chargés ({time.time() - t0:.0f} s)")
    if lot:
        con.executemany("INSERT INTO passages (pid, source, famille, doc_id, ref, titre, section, date, statut, "
                        "statut_detail, poids, texte, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", lot)
    con.commit()
    print("  construction de l'index de recherche (quelques minutes)...")
    con.executescript("""
        CREATE INDEX i_source ON passages(source);
        CREATE INDEX i_doc ON passages(doc_id);
        CREATE VIRTUAL TABLE fts USING fts5(titre, texte, content='passages', content_rowid='id',
                                            tokenize='unicode61 remove_diacritics 2');
        INSERT INTO fts(fts) VALUES('rebuild');
    """)
    con.commit()
    par_source = con.execute("SELECT source, COUNT(*), COUNT(DISTINCT doc_id) FROM passages GROUP BY source ORDER BY 1").fetchall()
    con.execute("ANALYZE")
    con.close()
    out = [f"Passages indexés : {n} en {time.time() - t0:.0f} s | taille de la base : {BASE.stat().st_size / 1e6:.0f} Mo",
           "Source | passages | documents"] + [f"{s} | {a} | {b}" for s, a, b in par_source]
    texte = "\n".join(out)
    (DONNEES / "index" / "controle_index.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nL'index est prêt. Prochaine étape : python chercher.py \"votre question\"")


if __name__ == "__main__":
    main()
