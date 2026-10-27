#!/usr/bin/env python3
"""
Index des Bulletins officiels des douanes (BOD) publiés sur douane.gouv.fr.

Utilisation :  python bod_liste.py
Parcourt la liste paginée des BOD (environ 340 pages, 1 requête par seconde), enregistre les pages brutes
et construit l'index. Reprise possible (les pages déjà enregistrées ne sont pas redemandées).

Résultats dans  donnees\\bod\\ :
   pages\\page_000.html ...   pages brutes de la liste
   index_bod.json            un enregistrement par BOD : numéro, date, classement, décisions, lien
   controle_index_bod.txt    rapport de contrôle
"""

import json
import re
import sys
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import requests

BASE = "https://www.douane.gouv.fr"
LISTE = BASE + "/bulletins-officiels-des-douanes?page=%d"
DOSSIER = Path("donnees") / "bod"
PAGES = DOSSIER / "pages"
ENTETES = {"User-Agent": "ia-juridique-prototype/0.1 (usage interne ; contact : jacek.gregory@orange.fr)"}
DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
DA = re.compile(r"\b(\d{2}-\d{3})\b")
CLASSEMENT = re.compile(r"\b([A-Z]\.\d+(?:\.\d+)*)\s*-\s*([^|\n]+)")


class Liste(HTMLParser):
    """Extrait, dans l'ordre du document, les liens et les fragments de texte."""

    def __init__(self):
        super().__init__()
        self.elements, self._href, self._texte = [], None, []

    BLOCS = {"div", "p", "li", "ul", "ol", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "br",
             "span", "time", "article", "section", "strong", "em", "b", "dd", "dt", "table"}

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._vider()
            self._href = dict(attrs).get("href")
        elif tag in self.BLOCS:
            self._vider()

    def handle_endtag(self, tag):
        if tag == "a":
            self._vider(lien=True)
        elif tag in self.BLOCS:
            self._vider()

    def handle_data(self, data):
        self._texte.append(data)

    def _vider(self, lien=False):
        t = re.sub(r"\s+", " ", "".join(self._texte).replace("\xa0", " ")).strip()
        if lien and self._href:
            self.elements.append(("lien", self._href, t))
            self._href = None
        elif t:
            self.elements.append(("texte", None, t))
        self._texte = []

    def close(self):
        self._vider()
        super().close()


def analyser(html):
    """Découpe une page de liste en entrées (une par lien /bod/NNNN)."""
    p = Liste()
    p.feed(html)
    p.close()
    entrees, courante = [], None
    for genre, href, texte in p.elements:
        m = re.search(r"/bod/(\d+)", href or "") if genre == "lien" else None
        if m:
            if courante and courante["numero"] == int(m.group(1)):
                courante["lignes"].append(texte)      # second lien vers le même BOD
                continue
            courante = {"numero": int(m.group(1)), "lien": BASE + href if href.startswith("/") else href,
                        "lignes": [texte] if texte else [], "decisions": []}
            entrees.append(courante)
            continue
        if courante is None:
            continue
        if genre == "lien" and "/da/" in (href or ""):
            courante["decisions"].append({"id": texte, "lien": BASE + href if href.startswith("/") else href})
        if texte:
            courante["lignes"].append(texte)
    for e in entrees:
        bloc = " | ".join(e["lignes"])
        d = DATE.search(bloc)
        e["date"] = f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None
        c = CLASSEMENT.search(bloc)
        e["classement"] = (c.group(1) + " - " + c.group(2).strip()) if c else None
        ids = {x["id"] for x in e["decisions"]}
        for ref in DA.findall(bloc):
            if ref not in ids:
                e["decisions"].append({"id": ref, "lien": None})
                ids.add(ref)
        e["intitules"] = [l for l in e["lignes"] if len(l) > 12 and not DATE.fullmatch(l)][:6]
    return entrees


def telecharger_page(n):
    chemin = PAGES / f"page_{n:03d}.html"
    if chemin.exists() and chemin.stat().st_size > 2000:
        return chemin.read_text(encoding="utf-8", errors="replace")
    for _ in range(4):
        try:
            r = requests.get(LISTE % n, headers=ENTETES, timeout=60)
        except requests.RequestException:
            time.sleep(5)
            continue
        if r.status_code == 200:
            chemin.write_text(r.text, encoding="utf-8")
            time.sleep(1.0)
            return r.text
        if r.status_code in (429, 500, 502, 503):
            time.sleep(10)
            continue
        break
    return None


def main():
    PAGES.mkdir(parents=True, exist_ok=True)
    tout, vides_de_suite, n = {}, 0, 0
    while n < 600:
        html = telecharger_page(n)
        entrees = analyser(html) if html else []
        for e in entrees:
            tout[e["numero"]] = e
        vides_de_suite = vides_de_suite + 1 if not entrees else 0
        if vides_de_suite >= 2:
            break
        if n % 25 == 0:
            print(f"  page {n} : {len(tout)} BOD au total")
        n += 1
    index = sorted(tout.values(), key=lambda e: e["numero"])
    (DOSSIER / "index_bod.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    sortie = [f"Pages parcourues : {n} | BOD distincts : {len(index)}"]
    if index:
        sortie.append(f"Numéros de {index[0]['numero']} à {index[-1]['numero']}")
    sans_date = [e["numero"] for e in index if not e["date"]]
    sans_classement = [e["numero"] for e in index if not e["classement"]]
    sortie.append(f"Sans date : {len(sans_date)} {sans_date[:10]} | sans classement : {len(sans_classement)} {sans_classement[:10]}")
    sortie.append(f"Avec au moins une décision (DA) : {sum(1 for e in index if e['decisions'])}")
    par_annee = Counter((e["date"] or "????")[:4] for e in index)
    sortie.append("Par année : " + " | ".join(f"{a}: {k}" for a, k in sorted(par_annee.items())))
    sortie.append("\n=== Exemples bruts (3 premiers, 3 derniers) ===")
    for e in index[:3] + index[-3:]:
        sortie.append(json.dumps({k: e[k] for k in ("numero", "date", "classement", "decisions", "intitules", "lien")},
                                 ensure_ascii=False))
    texte = "\n".join(sortie)
    (DOSSIER / "controle_index_bod.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\bod\\controle_index_bod.txt).")


if __name__ == "__main__":
    sys.exit(main())
