#!/usr/bin/env python3
"""
Reconnaissance de caractères (OCR, Tesseract en français) des PDF numérisés de la doctrine (BOD).

Prérequis (une seule fois) :
   1. Installer Tesseract pour Windows (version « UB Mannheim ») en cochant la langue FRENCH :
        https://github.com/UB-Mannheim/tesseract/wiki
      (chemin habituel : C:\\Program Files\\Tesseract-OCR)
   2. pip install pytesseract pillow pymupdf

Utilisation :
   python da_ocr.py echantillon    # 6 fichiers de périodes variées : vérifie l'installation, la vitesse et la qualité
   python da_ocr.py                # tous les PDF numérisés (reprise possible)
   python da_ocr.py tout 4         # idem avec 4 processus en parallèle (par défaut : moitié des cœurs)

Lit      :  donnees\\bod\\textes_manifest.json   (fichiers de statut « scan »)
Écrit    :  donnees\\bod\\textes\\<identifiant DA>.txt
            donnees\\bod\\textes_manifest.json   (statut « ok_ocr », « ocr_faible » ou « erreur_ocr »)
            donnees\\bod\\controle_ocr.txt
"""

import os

os.environ.setdefault("OMP_THREAD_LIMIT", "1")   # un seul fil par processus Tesseract

import json
import re
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

DOSSIER = Path("donnees") / "bod"
TEXTES = DOSSIER / "textes"
LANGUE = os.environ.get("OCR_LANGUE", "fra")
DPI = 300
MAX_PAGES = 80
CHEMINS_WINDOWS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                   r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                   str(Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe")]


def configurer_tesseract():
    import pytesseract
    if shutil.which("tesseract") is None:
        for c in CHEMINS_WINDOWS:
            if Path(c).exists():
                pytesseract.pytesseract.tesseract_cmd = c
                break
    return pytesseract


def verifier_installation():
    try:
        pyt = configurer_tesseract()
        version = pyt.get_tesseract_version()
        langues = pyt.get_languages()
    except Exception as e:
        sys.exit("Tesseract est introuvable ou inutilisable (" + str(e)[:120] + ").\n"
                 "Installez-le : https://github.com/UB-Mannheim/tesseract/wiki  (cochez la langue French), "
                 "puis lancez : pip install pytesseract pillow pymupdf")
    if LANGUE not in langues:
        sys.exit(f"La langue « {LANGUE} » n'est pas installée dans Tesseract (langues trouvées : {langues}).\n"
                 "Relancez l'installateur de Tesseract et cochez French dans « Additional language data ».")
    print(f"Tesseract {version}, langue {LANGUE} : prêt")


def pages_en_images(chemin, dpi=DPI):
    """Génère les pages du PDF sous forme d'images (PyMuPDF, ou pypdfium2 à défaut)."""
    from PIL import Image
    try:
        import fitz
        with fitz.open(str(chemin)) as doc:
            for i, page in enumerate(doc):
                if i >= MAX_PAGES:
                    break
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                yield Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    except ImportError:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(chemin))
        for i in range(min(len(pdf), MAX_PAGES)):
            yield pdf[i].render(scale=dpi / 72).to_pil().convert("RGB")


def traiter(args):
    """Exécuté dans un processus séparé : OCR d'un fichier."""
    ident, chemin = args
    debut = time.time()
    try:
        pyt = configurer_tesseract()
        pages = []
        for image in pages_en_images(chemin):
            pages.append(pyt.image_to_string(image.convert("L"), lang=LANGUE))
        texte = "\n\n".join(pages)
        texte = re.sub(r"[ \t]+\n", "\n", texte.replace("\x0c", "\n"))
        texte = re.sub(r"\n{3,}", "\n\n", texte).strip()
        return {"id": ident, "texte": texte, "pages": len(pages), "duree": round(time.time() - debut, 1)}
    except Exception as e:
        return {"id": ident, "erreur": str(e)[:160], "duree": round(time.time() - debut, 1)}


def qualite(texte, pages):
    lettres = sum(c.isalpha() for c in texte)
    non_blancs = sum(not c.isspace() for c in texte) or 1
    return lettres / non_blancs, len(texte) / max(1, pages)


def main():
    argv = [a for a in sys.argv[1:]]
    mode = argv[0] if argv else "tout"
    processus = int(argv[1]) if len(argv) > 1 else max(1, (os.cpu_count() or 2) // 2)
    verifier_installation()
    TEXTES.mkdir(parents=True, exist_ok=True)
    chemin_manifeste = DOSSIER / "textes_manifest.json"
    manifeste = {r["id"]: r for r in json.loads(chemin_manifeste.read_text(encoding="utf-8"))}
    scans = [r for r in manifeste.values() if r["statut"] == "scan" or
             (mode == "echantillon" and r["statut"] in ("ok_ocr", "ocr_faible", "erreur_ocr"))]
    if mode == "echantillon":
        scans = [r for r in manifeste.values() if r["statut"] in ("scan", "ok_ocr", "ocr_faible", "erreur_ocr")]
        pas = max(1, len(scans) // 6)
        scans = sorted(scans, key=lambda r: r["date_publication"] or "")[::pas][:6]
    print(f"PDF numérisés à traiter : {len(scans)} | processus en parallèle : {processus}")

    t0, faits, resultats = time.time(), 0, []
    with ProcessPoolExecutor(max_workers=processus) as pool:
        futurs = {pool.submit(traiter, (r["id"], r["fichier"])): r for r in scans}
        for f in as_completed(futurs):
            res, r = f.result(), futurs[f]
            faits += 1
            if "erreur" in res:
                r.update(statut="erreur_ocr", detail=res["erreur"])
            else:
                ratio, par_page = qualite(res["texte"], res["pages"])
                (TEXTES / f"{r['id']}.txt").write_text(res["texte"], encoding="utf-8")
                r.update(statut="ok_ocr" if (ratio >= 0.6 and par_page >= 300) else "ocr_faible",
                         methode=f"tesseract {LANGUE} {DPI}dpi", pages=res["pages"], caracteres=len(res["texte"]),
                         part_lettres=round(ratio, 2), duree_s=res["duree"])
            manifeste[r["id"]] = r
            resultats.append(r)
            if faits % 25 == 0:
                ecoule = time.time() - t0
                print(f"  {faits}/{len(scans)} traités ({ecoule / 60:.1f} min, reste ~{ecoule / faits * (len(scans) - faits) / 60:.0f} min)")
                chemin_manifeste.write_text(json.dumps(list(manifeste.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    chemin_manifeste.write_text(json.dumps(list(manifeste.values()), ensure_ascii=False, indent=1), encoding="utf-8")

    pages = sum(r.get("pages", 0) for r in resultats)
    out = [f"Fichiers traités : {len(resultats)} en {(time.time() - t0) / 60:.1f} min | pages : {pages} | "
           f"{(time.time() - t0) / max(1, pages):.1f} s par page (avec {processus} processus)",
           "Statuts : " + " | ".join(f"{k}: {v}" for k, v in Counter(r["statut"] for r in resultats).most_common()),
           f"Caractères reconnus : {sum(r.get('caracteres', 0) for r in resultats):,}".replace(",", " ")]
    faibles = [r for r in resultats if r["statut"] in ("ocr_faible", "erreur_ocr")]
    out.append(f"\n=== Qualité faible ou erreur ({len(faibles)}) ===")
    out += [f"   {r['id']} | {r['statut']} | pages {r.get('pages')} | car. {r.get('caracteres')} | lettres {r.get('part_lettres')} "
            f"| {r.get('detail', '')}" for r in faibles[:15]]
    out.append("\n=== Exemples de texte reconnu ===")
    for r in [x for x in resultats if x["statut"] == "ok_ocr"][:5]:
        t = (TEXTES / f"{r['id']}.txt").read_text(encoding="utf-8")
        out.append(f"--- DA {r['id']} ({r['date_publication']}, {r['pages']} p., {r['caracteres']} car., lettres {r['part_lettres']}) : {t[:420]!r}")
    texte = "\n".join(out)
    (DOSSIER / "controle_ocr.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\bod\\controle_ocr.txt).")


if __name__ == "__main__":
    main()
