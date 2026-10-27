#!/usr/bin/env python3
"""
Extraction du texte des fichiers principaux des décisions administratives (DA) du BOD.

Prérequis (une fois) :   pip install pymupdf striprtf
   (facultatif, pour les anciens .doc :  pip install pywin32  si Microsoft Word est installé,
    ou bien installer LibreOffice)

Utilisation :
   python da_extraire.py echantillon    # 40 fichiers de types et d'époques variés
   python da_extraire.py                # tous les fichiers (reprise possible)

Lit      :  donnees\\bod\\fichiers_manifest.json
Écrit    :  donnees\\bod\\textes\\<identifiant DA>.txt
            donnees\\bod\\textes_manifest.json   (statut de chaque fichier : ok, scan, court, non_converti, erreur)
            donnees\\bod\\controle_extraction.txt
Les PDF numérisés (sans texte) sont signalés « scan » : ils demanderont une reconnaissance de caractères (OCR).
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

DOSSIER = Path("donnees") / "bod"
TEXTES = DOSSIER / "textes"
SEUIL_PAGE_SCAN = 100   # moins de 100 caractères par page en moyenne : probablement une image
SEUIL_COURT = 200       # moins de 200 caractères au total : texte vide ou presque


# ---------------------------------------------------------------- PDF
def texte_pdf(chemin):
    """Renvoie (texte, nombre de pages, méthode)."""
    try:
        import fitz  # PyMuPDF
        with fitz.open(str(chemin)) as doc:
            pages = [p.get_text() for p in doc]
        return "\n".join(pages), len(pages), "pymupdf"
    except ImportError:
        pass
    from pypdf import PdfReader
    lecteur = PdfReader(str(chemin))
    pages = [(p.extract_text() or "") for p in lecteur.pages]
    return "\n".join(pages), len(pages), "pypdf"


# ---------------------------------------------------------------- DOCX / ODT / RTF (sans dépendance lourde)
def texte_docx(chemin):
    with zipfile.ZipFile(chemin) as z:
        racine = ET.fromstring(z.read("word/document.xml"))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphes = []
    for p in racine.iter(ns + "p"):
        morceaux = []
        for e in p.iter():
            if e.tag == ns + "t" and e.text:
                morceaux.append(e.text)
            elif e.tag in (ns + "tab",):
                morceaux.append("\t")
            elif e.tag in (ns + "br",):
                morceaux.append("\n")
        paragraphes.append("".join(morceaux))
    return "\n".join(paragraphes)


def texte_odt(chemin):
    with zipfile.ZipFile(chemin) as z:
        racine = ET.fromstring(z.read("content.xml"))
    ns_texte = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    lignes = []
    for e in racine.iter():
        if e.tag in (ns_texte + "p", ns_texte + "h"):
            lignes.append("".join(e.itertext()))
    return "\n".join(lignes)


def texte_rtf(chemin):
    brut = Path(chemin).read_bytes().decode("latin-1", errors="replace")
    try:
        from striprtf.striprtf import rtf_to_text
        return rtf_to_text(brut)
    except ImportError:
        brut = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), brut)
        brut = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", brut)
        return brut


# ---------------------------------------------------------------- anciens .doc (OLE) : Word ou LibreOffice
class ConvertisseurDoc:
    def __init__(self):
        self.word = None
        self.soffice = None
        self.methode = None
        try:
            import win32com.client  # type: ignore
            self.word = win32com.client.DispatchEx("Word.Application")
            self.word.Visible = False
            self.word.DisplayAlerts = 0
            self.methode = "word"
        except Exception:
            self.word = None
        if not self.word:
            self.soffice = shutil.which("soffice") or shutil.which("libreoffice")
            if not self.soffice:
                for c in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                          r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
                    if Path(c).exists():
                        self.soffice = c
                        break
            if self.soffice:
                self.methode = "libreoffice"

    def convertir(self, chemin):
        chemin = Path(chemin).resolve()
        if self.word:
            doc = self.word.Documents.Open(str(chemin), ReadOnly=True, AddToRecentFiles=False,
                                           ConfirmConversions=False, Visible=False)
            try:
                return doc.Content.Text.replace("\r", "\n")
            finally:
                doc.Close(False)
        if self.soffice:
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run([self.soffice, "--headless", "--convert-to", "txt:Text (encoded):UTF8",
                                "--outdir", tmp, str(chemin)], timeout=180, capture_output=True)
                sortie = Path(tmp) / (chemin.stem + ".txt")
                if sortie.exists():
                    return sortie.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError("conversion LibreOffice sans résultat")
        raise RuntimeError("ni Word ni LibreOffice disponible")

    def fermer(self):
        if self.word:
            try:
                self.word.Quit()
            except Exception:
                pass


# ---------------------------------------------------------------- orchestrateur
def type_reel(chemin):
    """Type d'après le contenu du fichier (et non l'extension, parfois trompeuse)."""
    debut = Path(chemin).read_bytes()[:8]
    if debut.startswith(b"%PDF"):
        return "pdf"
    if debut.startswith(b"PK"):
        with zipfile.ZipFile(chemin) as z:
            noms = z.namelist()
        if "word/document.xml" in noms:
            return "docx"
        if "content.xml" in noms:
            return "odt"
        return "zip"
    if debut.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole"   # ancien .doc ou .xls
    if debut.startswith(b"{\\rtf"):
        return "rtf"
    return "inconnu"


def nettoyer(t):
    t = t.replace("\x00", "").replace("\x0c", "\n").replace("\xa0", " ").replace("\ufeff", "")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def main():
    TEXTES.mkdir(parents=True, exist_ok=True)
    fichiers = [m for m in json.loads((DOSSIER / "fichiers_manifest.json").read_text(encoding="utf-8")) if m.get("ok")]
    mode = sys.argv[1] if len(sys.argv) > 1 else "tout"
    if mode == "echantillon":
        par_type = {}
        for m in fichiers:
            par_type.setdefault(m["ext"], []).append(m)
        choisis = []
        for ext, liste in par_type.items():
            pas = max(1, len(liste) // (25 if ext == "pdf" else 8))
            choisis += liste[::pas][: (25 if ext == "pdf" else 8)]
        fichiers = choisis[:40]
    print(f"Fichiers à traiter : {len(fichiers)}")

    chemin_manifeste = DOSSIER / "textes_manifest.json"
    resultats = {r["id"]: r for r in json.loads(chemin_manifeste.read_text(encoding="utf-8"))} \
        if chemin_manifeste.exists() else {}
    conv = None
    for k, m in enumerate(fichiers, 1):
        ident = m["id"]
        if ident in resultats and resultats[ident]["statut"] in ("ok", "court", "scan") and mode != "echantillon":
            continue
        chemin = Path(m["chemin"])
        r = {"id": ident, "fichier": str(chemin), "titre": m.get("titre"), "date_publication": m.get("date_publication"),
             "classement": m.get("classement"), "ext": m["ext"]}
        try:
            reel = type_reel(chemin)
            r["type_reel"] = reel
            pages = None
            if reel == "pdf":
                texte, pages, methode = texte_pdf(chemin)
            elif reel == "docx":
                texte, methode = texte_docx(chemin), "xml docx"
            elif reel == "odt":
                texte, methode = texte_odt(chemin), "xml odt"
            elif reel == "rtf":
                texte, methode = texte_rtf(chemin), "rtf"
            elif reel == "ole" and m["ext"] in ("doc", "rtf", "docx", "odt"):
                conv = conv or ConvertisseurDoc()
                texte, methode = conv.convertir(chemin), conv.methode
            else:
                raise RuntimeError(f"type non pris en charge : {reel}")
            texte = nettoyer(texte)
            r.update(methode=methode, pages=pages, caracteres=len(texte))
            if reel == "pdf" and pages and len(texte) / pages < SEUIL_PAGE_SCAN:
                r["statut"] = "scan"
            elif len(texte) < SEUIL_COURT:
                r["statut"] = "court"
            else:
                r["statut"] = "ok"
            if texte:
                (TEXTES / f"{ident}.txt").write_text(texte, encoding="utf-8")
        except Exception as e:
            r.update(statut="non_converti" if "ni Word" in str(e) else "erreur", detail=str(e)[:150])
        resultats[ident] = r
        if k % 200 == 0:
            print(f"  {k}/{len(fichiers)} traités")
            chemin_manifeste.write_text(json.dumps(list(resultats.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    if conv:
        conv.fermer()
    chemin_manifeste.write_text(json.dumps(list(resultats.values()), ensure_ascii=False, indent=1), encoding="utf-8")

    rs = [r for r in resultats.values() if r["id"] in {m["id"] for m in fichiers}]
    out = [f"Fichiers traités : {len(rs)}",
           "Statuts : " + " | ".join(f"{k}: {v}" for k, v in Counter(r["statut"] for r in rs).most_common()),
           "Types réels : " + " | ".join(f"{k}: {v}" for k, v in Counter(r.get("type_reel", "?") for r in rs).most_common()),
           "Méthodes : " + " | ".join(f"{k}: {v}" for k, v in Counter(r.get("methode", "—") for r in rs).most_common()),
           f"Caractères extraits au total : {sum(r.get('caracteres', 0) for r in rs):,}".replace(",", " ")]
    out.append("\nPar décennie et statut :")
    tab = Counter(((r["date_publication"] or "????")[:3] + "0", r["statut"]) for r in rs)
    for dec in sorted({d for d, _ in tab}):
        out.append(f"   {dec} : " + " | ".join(f"{s}: {tab[(dec, s)]}" for s in ("ok", "scan", "court", "non_converti", "erreur") if tab[(dec, s)]))
    problemes = [r for r in rs if r["statut"] in ("erreur", "non_converti")]
    out.append(f"\n=== Erreurs / non convertis ({len(problemes)}) ===")
    out += [f"   {r['id']} ({r['ext']}) : {r.get('detail', '')}" for r in problemes[:15]]
    out.append("\n=== Exemples de texte extrait ===")
    for r in [x for x in rs if x["statut"] == "ok"][:: max(1, len(rs) // 6)][:6]:
        t = (TEXTES / f"{r['id']}.txt").read_text(encoding="utf-8")
        out.append(f"--- DA {r['id']} ({r['date_publication']}, {r['type_reel']}, {r['caracteres']} car.) : {t[:260]!r}")
    texte = "\n".join(out)
    (DOSSIER / "controle_extraction.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\bod\\controle_extraction.txt).")


if __name__ == "__main__":
    sys.exit(main())
