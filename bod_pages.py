#!/usr/bin/env python3
"""
Lecture de la page de chaque BOD : décisions administratives, PDF (principal et annexes),
relations « abroge / remplace / modifie ». Aucun PDF n'est téléchargé à cette étape.

Utilisation :
   python bod_pages.py echantillon    # 25 bulletins répartis sur toute la période (2 minutes)
   python bod_pages.py                # tous les bulletins (environ 35 minutes, reprise possible)

Lit      :  donnees\\bod\\index_bod.json
Écrit    :  donnees\\bod\\bod_html\\<numéro>.html.gz   (pages brutes, pour pouvoir ajuster sans retélécharger)
            donnees\\bod\\bod_detail.json              (résultat)
            donnees\\bod\\controle_bod_pages.txt        (rapport)
"""

import gzip
import json
import re
import sys
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests

BASE = "https://www.douane.gouv.fr"
DOSSIER = Path("donnees") / "bod"
HTML = DOSSIER / "bod_html"
ENTETES = {"User-Agent": "ia-juridique-prototype/0.1 (usage interne ; contact : jacek.gregory@orange.fr)"}
FICHIER = re.compile(r"\.(pdf|ods|odt|doc|docx|xls|xlsx|zip|rtf|txt)(?:\?|$)", re.IGNORECASE)
DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
DA = re.compile(r"\b(\d{2}-\d{3})\b")
RELATION = re.compile(r"\b(abroge|abrogent|remplace|modifie|annule|complète|complete)\b", re.IGNORECASE)
BRUIT = ("Imprimer", "Envoyer par email", "Partager", "Retour à la liste", "Page précédente", "Première page",
         "Page courante", "Direction générale des douanes")


class Page(HTMLParser):
    BLOCS = {"div", "p", "li", "ul", "ol", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "br", "span",
             "time", "article", "section", "strong", "em", "b", "dd", "dt", "table", "nav", "header", "footer"}

    def __init__(self):
        super().__init__()
        self.elements, self._href, self._texte, self.titre_page, self._dans_titre = [], None, [], "", False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._dans_titre = True
        if tag == "a":
            self._vider()
            self._href = dict(attrs).get("href")
        elif tag in self.BLOCS:
            self._vider()

    def handle_endtag(self, tag):
        if tag == "title":
            self._dans_titre = False
        if tag == "a":
            self._vider(lien=True)
        elif tag in self.BLOCS:
            self._vider()

    def handle_data(self, data):
        if self._dans_titre:
            self.titre_page += data
        else:
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


def analyser(html, numero):
    p = Page()
    p.feed(html)
    p.close()
    lignes = [t for g, _, t in p.elements if g == "texte" and t and not any(b in t for b in BRUIT)]
    fichiers, decisions, vus = [], [], set()
    for genre, href, texte in p.elements:
        if genre != "lien" or not href:
            continue
        url = urljoin(BASE, href)
        if FICHIER.search(href):
            if url not in vus:
                vus.add(url)
                fichiers.append({"url": url, "nom": unquote(url.rsplit("/", 1)[-1]), "texte_du_lien": texte})
        elif "/da/" in href:
            decisions.append({"id": texte or href.rsplit("/", 1)[-1], "url": url})
    # décision principale : le fichier dont le nom commence par le numéro de la décision, sinon le premier PDF
    ids = [d["id"] for d in decisions] or sorted(set(DA.findall(" ".join(lignes))))
    for f in fichiers:
        f["role"] = "annexe"
    principal = next((f for f in fichiers if any(f["nom"].startswith(i) for i in ids)), None) \
        or next((f for f in fichiers if f["nom"].lower().endswith(".pdf")), None)
    if principal:
        principal["role"] = "principal"
    relations = [l for l in lignes if RELATION.search(l) and len(l) < 400][:12]
    bloc = " | ".join(lignes)
    d = DATE.search(bloc)
    return {
        "numero": numero,
        "titre_page": re.sub(r"\s+", " ", p.titre_page).strip(),
        "date": f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None,
        "decisions": decisions or [{"id": i, "url": None} for i in ids],
        "fichiers": fichiers,
        "relations": relations,
        "lignes": lignes[:60],
    }


def page(numero, lien):
    chemin = HTML / f"{numero}.html.gz"
    if chemin.exists():
        return gzip.decompress(chemin.read_bytes()).decode("utf-8", errors="replace")
    for _ in range(4):
        try:
            r = requests.get(lien, headers=ENTETES, timeout=60)
        except requests.RequestException:
            time.sleep(5)
            continue
        if r.status_code == 200:
            chemin.write_bytes(gzip.compress(r.text.encode("utf-8")))
            time.sleep(0.7)
            return r.text
        if r.status_code in (429, 500, 502, 503):
            time.sleep(10)
            continue
        return None
    return None


def main():
    HTML.mkdir(parents=True, exist_ok=True)
    index = json.loads((DOSSIER / "index_bod.json").read_text(encoding="utf-8"))
    mode = sys.argv[1] if len(sys.argv) > 1 else "tout"
    if mode == "echantillon":
        pas = max(1, len(index) // 25)
        index = index[::pas][:25] + index[-3:]
    detail, echecs = [], []
    for k, e in enumerate(index, 1):
        html = page(e["numero"], e["lien"])
        if html is None:
            echecs.append(e["numero"])
            continue
        r = analyser(html, e["numero"])
        r["date_index"] = e["date"]
        detail.append(r)
        if k % 100 == 0:
            print(f"  {k}/{len(index)} pages lues, {len(echecs)} échecs")
    nom = "bod_detail_echantillon.json" if mode == "echantillon" else "bod_detail.json"
    (DOSSIER / nom).write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")

    out = [f"BOD lus : {len(detail)} | échecs : {len(echecs)} {echecs[:15]}"]
    sans_fichier = [d["numero"] for d in detail if not d["fichiers"]]
    out.append(f"BOD sans aucun fichier joint : {len(sans_fichier)} {sans_fichier[:15]}")
    sans_principal = [d["numero"] for d in detail if d["fichiers"] and not any(f["role"] == "principal" for f in d["fichiers"])]
    out.append(f"BOD avec fichiers mais sans PDF principal identifié : {len(sans_principal)} {sans_principal[:15]}")
    ext = Counter(f["nom"].rsplit(".", 1)[-1].lower() for d in detail for f in d["fichiers"])
    out.append("Types de fichiers : " + " | ".join(f"{k}: {v}" for k, v in ext.most_common()))
    out.append(f"Nombre total de fichiers : {sum(len(d['fichiers']) for d in detail)} "
               f"(dont principaux : {sum(1 for d in detail for f in d['fichiers'] if f['role'] == 'principal')})")
    out.append(f"BOD avec une relation abroge/remplace/modifie : {sum(1 for d in detail if d['relations'])}")
    sans_date = [d["numero"] for d in detail if not d["date"]]
    out.append(f"BOD sans date lue sur la page : {len(sans_date)}")
    out.append("\n=== Exemples (par ancienneté) ===")
    for d in detail[:: max(1, len(detail) // 8)][:9]:
        out.append(f"--- BOD {d['numero']} ({d['date_index']}) — {d['titre_page'][:90]}")
        out.append(f"    décisions : {[x['id'] for x in d['decisions']][:5]}")
        out.append(f"    fichiers : {[(f['role'], f['nom'][:60]) for f in d['fichiers']][:4]} (total {len(d['fichiers'])})")
        out.append(f"    relations : {d['relations'][:2]}")
        out.append(f"    début : {d['lignes'][:8]}")
    texte = "\n".join(out)
    (DOSSIER / "controle_bod_pages.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\bod\\controle_bod_pages.txt).")


if __name__ == "__main__":
    sys.exit(main())
