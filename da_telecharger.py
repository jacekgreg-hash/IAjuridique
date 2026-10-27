#!/usr/bin/env python3
"""
Téléchargement des fichiers principaux des décisions administratives (DA) du BOD.
(Les annexes ne sont pas téléchargées à cette étape.)

Utilisation :
   python da_telecharger.py echantillon    # 15 fichiers de périodes variées (1 minute)
   python da_telecharger.py                # tous les fichiers principaux (environ 30 minutes, reprise possible)

Lit      :  donnees\\bod\\da_detail.json
Écrit    :  donnees\\bod\\fichiers\\<identifiant DA>\\<nom du fichier>
            donnees\\bod\\fichiers_manifest.json   (un enregistrement par fichier)
            donnees\\bod\\controle_telechargement.txt
"""

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests

DOSSIER = Path("donnees") / "bod"
FICHIERS = DOSSIER / "fichiers"
ENTETES = {"User-Agent": "ia-juridique-prototype/0.1 (usage interne ; contact : jacek.gregory@orange.fr)"}
MAGIQUES = {"pdf": b"%PDF", "docx": b"PK", "odt": b"PK", "ods": b"PK", "xlsx": b"PK", "zip": b"PK",
            "doc": b"\xd0\xcf\x11\xe0", "xls": b"\xd0\xcf\x11\xe0", "rtf": b"{\\rtf"}


def nom_sur(nom):
    """Nom de fichier compatible Windows (caractères interdits remplacés, longueur limitée)."""
    nom = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nom).strip(" .")
    base, _, ext = nom.rpartition(".")
    if not base:
        base, ext = nom, ""
    return (base[:90] + ("." + ext if ext else "")) or "fichier"


def contenu_valide(contenu, ext):
    magique = MAGIQUES.get(ext)
    return len(contenu) > 200 and (magique is None or contenu[:8].startswith(magique) or
                                   (ext in ("doc", "xls") and contenu[:2] == b"PK") or
                                   (ext == "rtf" and contenu.lstrip()[:5] == b"{\\rtf"))


def main():
    detail = json.loads((DOSSIER / "da_detail.json").read_text(encoding="utf-8"))
    cibles = []
    for d in detail:
        p = next((f for f in d["fichiers"] if f["role"] == "principal"), None)
        if p:
            cibles.append((d, p))
    mode = sys.argv[1] if len(sys.argv) > 1 else "tout"
    if mode == "echantillon":
        pas = max(1, len(cibles) // 15)
        cibles = cibles[::pas][:15]
    print(f"Fichiers principaux à télécharger : {len(cibles)}")

    chemin_manifeste = DOSSIER / "fichiers_manifest.json"
    manifeste = {m["id"]: m for m in json.loads(chemin_manifeste.read_text(encoding="utf-8"))} \
        if chemin_manifeste.exists() else {}
    echecs, octets = [], 0
    for k, (d, f) in enumerate(cibles, 1):
        ident = d["id"]
        ext = f["nom"].rsplit(".", 1)[-1].lower()
        cible = FICHIERS / ident / nom_sur(f["nom"])
        if ident in manifeste and manifeste[ident].get("ok") and Path(manifeste[ident]["chemin"]).exists():
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        contenu, statut = None, "aucune réponse"
        for _ in range(4):
            try:
                r = requests.get(f["url"], headers=ENTETES, timeout=120)
            except requests.RequestException as e:
                statut = str(e)[:100]
                time.sleep(5)
                continue
            if r.status_code == 200 and contenu_valide(r.content, ext):
                contenu = r.content
                break
            statut = f"code {r.status_code}, {len(r.content)} octets"
            if r.status_code in (429, 500, 502, 503) or r.status_code == 200:
                time.sleep(6)
                continue
            break
        if contenu is None:
            echecs.append((ident, f["url"], statut))
            manifeste[ident] = {"id": ident, "ok": False, "url": f["url"], "détail": statut}
        else:
            cible.write_bytes(contenu)
            octets += len(contenu)
            manifeste[ident] = {"id": ident, "ok": True, "url": f["url"], "chemin": str(cible), "ext": ext,
                                "taille": len(contenu), "date_publication": d["date_publication"],
                                "titre": d["titre"], "classement": d["classement"]}
        if k % 100 == 0:
            print(f"  {k}/{len(cibles)} traités, {len(echecs)} échecs, {octets / 1e6:.0f} Mo téléchargés")
            chemin_manifeste.write_text(json.dumps(list(manifeste.values()), ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(0.4)
    chemin_manifeste.write_text(json.dumps(list(manifeste.values()), ensure_ascii=False, indent=1), encoding="utf-8")

    ok = [m for m in manifeste.values() if m.get("ok")]
    out = [f"Fichiers principaux visés : {len(cibles)} | enregistrés au total : {len(ok)} | échecs : {len(echecs)}",
           f"Taille totale : {sum(m['taille'] for m in ok) / 1e6:.0f} Mo",
           "Par type : " + " | ".join(f"{k}: {v}" for k, v in Counter(m["ext"] for m in ok).most_common()),
           "Par décennie : " + " | ".join(f"{k}: {v}" for k, v in sorted(Counter(
               (m["date_publication"] or "????")[:3] + "0" for m in ok).items()))]
    out.append("\n=== Échecs ===")
    out += [f"   {i} | {u[-80:]} | {s}" for i, u, s in echecs[:30]]
    texte = "\n".join(out)
    (DOSSIER / "controle_telechargement.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\bod\\controle_telechargement.txt).")


if __name__ == "__main__":
    sys.exit(main())
