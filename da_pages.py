#!/usr/bin/env python3
"""
Lecture de la page de chaque décision administrative (DA) du BOD : métadonnées, statut (abrogée par / abroge /
modifie...), fichiers (PDF principal et annexes). Aucun PDF n'est téléchargé à cette étape.

Utilisation :
   python da_pages.py echantillon    # 30 décisions réparties sur toute la période (2 minutes)
   python da_pages.py                # toutes les décisions (environ 1 heure, reprise possible)

Lit      :  donnees\\bod\\index_bod.json
Écrit    :  donnees\\bod\\da_html\\<identifiant>.html.gz   (pages brutes, pour ajuster sans retélécharger)
            donnees\\bod\\da_detail.json (ou da_detail_echantillon.json)
            donnees\\bod\\controle_da_pages.txt
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
URL_DA = BASE + "/la-douane/informations/bulletins-officiels-des-douanes/da/%s"
DOSSIER = Path("donnees") / "bod"
HTML = DOSSIER / "da_html"
ENTETES = {"User-Agent": "ia-juridique-prototype/0.1 (usage interne ; contact : jacek.gregory@orange.fr)"}
FICHIER = re.compile(r"\.(pdf|ods|odt|doc|docx|xls|xlsx|zip|rtf|txt)(?:\?|$)", re.IGNORECASE)
DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
VERBE = re.compile(r"(est abrogée par|est abrogé par|abroge|est modifiée par|modifie|est remplacée par|remplace|"
                   r"est complétée par|complète|annule)", re.IGNORECASE)
BRUIT = ("Imprimer", "Envoyer par email", "Partager", "Retour à la liste", "Mon Espace Personnel", "RGPD")
BANDEAU = {"douane.gouv.fr", "Le portail de la direction générale des douanes et droits indirects", "Fermer",
           "Engagements et qualité", "Mon Espace Personnel", "RGPD"}


class Page(HTMLParser):
    BLOCS = {"div", "p", "li", "ul", "ol", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "br", "span",
             "time", "article", "section", "strong", "em", "b", "dd", "dt", "table", "nav", "header", "footer"}

    def __init__(self):
        super().__init__()
        self.elements, self._href, self._texte = [], None, []
        self.titre_page, self._dans_titre, self._ignorer = "", False, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._ignorer += 1
            return
        if tag == "title":
            self._dans_titre = True
        if tag == "a":
            self._vider()
            self._href = dict(attrs).get("href")
        elif tag in self.BLOCS:
            self._vider()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._ignorer = max(0, self._ignorer - 1)
            return
        if tag == "title":
            self._dans_titre = False
        if tag == "a":
            self._vider(lien=True)
        elif tag in self.BLOCS:
            self._vider()

    def handle_data(self, data):
        if self._ignorer:
            return
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


def analyser(html, ident):
    p = Page()
    p.feed(html)
    p.close()
    lignes = [t for g, _, t in p.elements if g == "texte" and t not in BANDEAU and not any(b in t for b in BRUIT)]
    relations, verbe, fichiers, vus, bod = [], None, [], set(), None
    for genre, href, texte in p.elements:
        if genre == "texte":
            m = VERBE.search(texte)
            if m and len(texte) < 120:
                verbe = m.group(1).lower()
            continue
        url = urljoin(BASE, href)
        if FICHIER.search(href):
            if url not in vus:
                vus.add(url)
                nom = unquote(url.rsplit("/", 1)[-1])
                fichiers.append({"url": url, "nom": nom, "texte_du_lien": texte, "role": "annexe"})
        elif re.search(r"/da/([\w-]+)", href) and ident not in href:
            cible = re.search(r"/da/([\w-]+)", href).group(1)
            relations.append({"relation": verbe or "non précisée", "da": cible, "intitule": texte, "url": url})
        elif re.search(r"/bod/(\d+)", href):
            bod = bod or int(re.search(r"/bod/(\d+)", href).group(1))
    # PDF principal : nom contenant l'identifiant ou commençant par « DA », sinon premier PDF
    cle = ident.lower()
    principal = next((f for f in fichiers if cle in f["nom"].lower()), None) \
        or next((f for f in fichiers if re.match(r"\s*(da|f\d?_|circulaire)", f["nom"], re.IGNORECASE)), None) \
        or next((f for f in fichiers if f["nom"].lower().endswith(".pdf")), None)
    if principal:
        principal["role"] = "principal"
    texte_page = " | ".join(lignes)
    dates = DATE.findall(texte_page)
    iso = lambda d: f"{d[2]}-{d[1]}-{d[0]}"
    classement = re.search(r"Classement\s*\|?\s*([^|]+)", texte_page)
    bureau = re.search(r"Bureau\s*\|?\s*([^|]+)", texte_page)
    titre = ""
    for i, l in enumerate(lignes):
        if re.match(r"^DA\s+\d{2}-\d{3}\b", l) and i > 0:
            titre = lignes[i - 1]
            break
    if not titre:
        titre = next((l for l in lignes if len(l) > 15 and not DATE.fullmatch(l)
                      and not l.startswith(("DA ", "BOD", "Classement", "Bureau", "Date", "Cette DA"))), "")
    return {
        "id": ident,
        "titre": titre,
        "titre_page": re.sub(r"\s+", " ", p.titre_page).strip(),
        "date_publication": iso(dates[0]) if dates else None,
        "date_entree_en_vigueur": iso(dates[1]) if len(dates) > 1 else (iso(dates[0]) if dates else None),
        "classement": classement.group(1).strip() if classement else None,
        "bureau": bureau.group(1).strip() if bureau else None,
        "bod": bod,
        "relations": relations,
        "abrogee_par": [r["da"] for r in relations if "abrogée par" in r["relation"] or "abrogé par" in r["relation"]],
        "fichiers": fichiers,
        "lignes": lignes[:80],
    }


def page(ident):
    chemin = HTML / f"{ident}.html.gz"
    if chemin.exists():
        return gzip.decompress(chemin.read_bytes()).decode("utf-8", errors="replace")
    for _ in range(4):
        try:
            r = requests.get(URL_DA % ident, headers=ENTETES, timeout=60)
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
    ids = []
    for e in index:
        for d in e["decisions"]:
            m = re.match(r"^\d{2}-\d{3}$", d["id"])
            if m and d["id"] not in ids:
                ids.append(d["id"])
    mode = sys.argv[1] if len(sys.argv) > 1 else "tout"
    if mode == "echantillon":
        pas = max(1, len(ids) // 30)
        ids = ids[::pas][:30] + ["24-069", "26-085", "93-004"]
    print(f"Décisions à lire : {len(ids)}")
    detail, echecs = [], []
    for k, ident in enumerate(ids, 1):
        html = page(ident)
        if html is None:
            echecs.append(ident)
        else:
            detail.append(analyser(html, ident))
        if k % 100 == 0:
            print(f"  {k}/{len(ids)} lues, {len(echecs)} échecs")
    nom = "da_detail_echantillon.json" if mode == "echantillon" else "da_detail.json"
    (DOSSIER / nom).write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")

    out = [f"Décisions lues : {len(detail)} | échecs : {len(echecs)} {echecs[:15]}"]
    sans_fichier = [d["id"] for d in detail if not d["fichiers"]]
    out.append(f"Sans aucun fichier (titre seul) : {len(sans_fichier)} {sans_fichier[:12]}")
    out.append("Types de fichiers : " + " | ".join(f"{k}: {v}" for k, v in Counter(
        f["nom"].rsplit(".", 1)[-1].lower() for d in detail for f in d["fichiers"]).most_common()))
    out.append(f"Décisions avec un fichier principal : {sum(1 for d in detail if any(f['role'] == 'principal' for f in d['fichiers']))}")
    out.append(f"Décisions abrogées (« est abrogée par ») : {sum(1 for d in detail if d['abrogee_par'])}")
    out.append("Relations : " + " | ".join(f"{k}: {v}" for k, v in Counter(
        r["relation"] for d in detail for r in d["relations"]).most_common()))
    out.append(f"Sans date : {sum(1 for d in detail if not d['date_publication'])} | sans classement : "
               f"{sum(1 for d in detail if not d['classement'])}")
    out.append("\n=== Exemples ===")
    for d in detail[:: max(1, len(detail) // 9)][:10] + [x for x in detail if x["id"] in ("24-069", "93-004")]:
        out.append(f"--- DA {d['id']} | {d['titre'][:90]} | publiée {d['date_publication']} | en vigueur {d['date_entree_en_vigueur']}")
        out.append(f"    classement : {d['classement']} | bureau : {d['bureau']} | BOD {d['bod']}")
        out.append(f"    relations : {[(r['relation'], r['da']) for r in d['relations']][:4]}")
        out.append(f"    fichiers : {[(f['role'], f['nom'][:50]) for f in d['fichiers']][:3]} (total {len(d['fichiers'])})")
        out.append(f"    début de page : {d['lignes'][:6]}")
    texte = "\n".join(out)
    (DOSSIER / "controle_da_pages.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\bod\\controle_da_pages.txt).")


if __name__ == "__main__":
    sys.exit(main())
