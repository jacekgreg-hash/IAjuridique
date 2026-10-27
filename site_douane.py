#!/usr/bin/env python3
"""
Récupération des pages d'information du site douane.gouv.fr (démarches et fiches pratiques : armes, stupéfiants,
déchets, formalités…), pour que l'assistant puisse répondre aux questions pratiques.

Utilisation :   python site_douane.py compter          # explore le site et compte les pages, sans rien garder de plus
                python site_douane.py telecharger     # explore et enregistre le texte des pages (reprise possible)
                python site_douane.py telecharger --pdf   # télécharge aussi les notices PDF liées (cerfa)
Options : --max NOMBRE (pages, défaut 4000)   --pause SECONDES (défaut 1.0)
Écrit :   donnees\\site_douane\\pages\\ (copies brutes)   donnees\\site_douane.jsonl   donnees\\site_douane\\controle_site_douane.txt

Courtoisie : respecte robots.txt, une requête par seconde, s'arrête en cas de refus répété.
Les pages du site sont des informations officielles, mais leurs conditions de réutilisation n'ont pas été vérifiées :
à confirmer avec votre service juridique avant tout usage au-delà de ce prototype interne.
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.robotparser
from collections import Counter, deque
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import requests

RACINE = "https://www.douane.gouv.fr"
DEPART = [RACINE + "/", RACINE + "/demarche", RACINE + "/fiche", RACINE + "/professionnel", RACINE + "/particulier"]
PREFIXES = ("/demarche/", "/fiche/", "/situation/", "/professionnel", "/particulier", "/actualite/")
DOSSIER = Path("donnees") / "site_douane"
SORTIE = Path("donnees") / "site_douane.jsonl"
IGNORE_BALISES = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg", "button", "select"}
BLOCS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "tr", "div", "br", "section", "article", "dt", "dd", "table"}


class Extracteur(HTMLParser):
    """Texte principal d'une page : contenu de <main> s'il existe, sinon de <body>, sans menus ni pieds de page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.profondeur_ignore = 0
        self.dans_main = 0
        self.a_main = False
        self.morceaux_main, self.morceaux_body = [], []
        self.titre, self.h1, self.h1_main, self.dans_titre, self.dans_h1 = "", "", "", False, False
        self.liens = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.dans_titre = True
        if tag == "h1":
            self.dans_h1 = True
        if tag == "a" and a.get("href"):
            self.liens.append(a["href"])
        if tag == "main":
            self.dans_main += 1
            self.a_main = True
        if tag in IGNORE_BALISES:
            self.profondeur_ignore += 1
        if tag in BLOCS:
            self._ajouter("\n")
        if tag in ("td", "th"):
            self._ajouter(" | ")

    def handle_endtag(self, tag):
        if tag == "title":
            self.dans_titre = False
        if tag == "h1":
            self.dans_h1 = False
        if tag == "main" and self.dans_main:
            self.dans_main -= 1
        if tag in IGNORE_BALISES and self.profondeur_ignore:
            self.profondeur_ignore -= 1
        if tag in BLOCS:
            self._ajouter("\n")

    def _ajouter(self, t):
        if self.profondeur_ignore:
            return
        self.morceaux_body.append(t)
        if self.dans_main:
            self.morceaux_main.append(t)

    def handle_data(self, data):
        if self.dans_titre:
            self.titre += data
        if self.dans_h1:
            self.h1 += data
            if self.dans_main:
                self.h1_main += data
        self._ajouter(data)

    def texte(self):
        brut = "".join(self.morceaux_main if self.a_main and self.morceaux_main else self.morceaux_body)
        lignes = [re.sub(r"[ \t\xa0]+", " ", l).strip(" |") for l in brut.split("\n")]
        sortie, vide = [], 0
        for l in lignes:
            if not l:
                vide += 1
                if vide == 1 and sortie:
                    sortie.append("")
                continue
            vide = 0
            sortie.append(l)
        return "\n".join(sortie).strip()


def analyser(html):
    e = Extracteur()
    e.feed(html)
    candidats = [e.h1_main, e.h1, e.titre]
    titre = ""
    for c in candidats:
        c = re.sub(r"\s+", " ", c).strip()
        if c and not c.lower().startswith("douane.gouv.fr"):
            titre = c
            break
    if not titre:  # titre générique du portail : on retombe sur l'avant-dernier segment de l'adresse
        titre = re.sub(r"\s+", " ", e.h1_main or e.h1 or e.titre).strip()
    titre = re.sub(r"\s*[|\-–]\s*douane\.gouv\.fr.*$", "", titre, flags=re.I)
    texte = e.texte()
    m = re.search(r"(?:mis[e]? à jour|mise à jour|dernière modification)[^0-9]{0,20}(\d{1,2})[/.](\d{1,2})[/.](\d{4})", texte, re.I)
    date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None
    return titre, texte, date, e.liens


def url_utile(url):
    p = urlparse(url)
    if p.netloc not in ("www.douane.gouv.fr", "douane.gouv.fr"):
        return None
    chemin = p.path
    if re.search(r"\.(?:jpg|jpeg|png|gif|svg|css|js|zip|xlsx?|docx?|odt|mp4)$", chemin, re.I):
        return None
    if chemin.lower().endswith(".pdf"):
        return "pdf" if "pdf" in sys.argv or "--pdf" in sys.argv else None
    if any(chemin.startswith(x) for x in PREFIXES):
        return "page"
    return None


def pdf_vers_texte(contenu):
    try:
        import fitz  # PyMuPDF, déjà utilisé pour la doctrine
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=contenu, filetype="pdf")
        return "\n".join(p.get_text() for p in doc).strip()
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["compter", "telecharger"])
    ap.add_argument("--max", type=int, default=4000)
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--pdf", action="store_true")
    a = ap.parse_args()

    (DOSSIER / "pages").mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (compatible; prototype-ia-juridique-interne; usage de recherche)"
    rp = urllib.robotparser.RobotFileParser()
    print("Lecture de robots.txt…", flush=True)
    try:
        r0 = s.get(RACINE + "/robots.txt", timeout=20)
        rp.parse(r0.text.splitlines() if r0.status_code == 200 else [])
        print(f"  robots.txt : code {r0.status_code}", flush=True)
    except requests.RequestException as e:
        print(f"  robots.txt illisible ({str(e)[:60]}), poursuite sans.", flush=True)
        rp.parse([])
    print("Exploration du site (une ligne s'affiche toutes les 10 pages téléchargées)…", flush=True)
    telecharges = 0
    file, vus, resultats, echecs = deque(DEPART), set(), [], []
    refus = 0
    while file and len(vus) < a.max:
        url = urldefrag(file.popleft())[0]
        url = url.rstrip("/") if url.rstrip("/") != RACINE else RACINE + "/"
        if url in vus:
            continue
        vus.add(url)
        genre = url_utile(url) or ("page" if url in DEPART else None)
        if not genre or not rp.can_fetch("*", url):
            continue
        cache = DOSSIER / "pages" / (hashlib.sha1(url.encode()).hexdigest() + (".pdf" if genre == "pdf" else ".html"))
        try:
            if cache.exists():
                contenu = cache.read_bytes()
            else:
                time.sleep(a.pause)
                r = s.get(url, timeout=20)
                telecharges += 1
                if telecharges <= 3 or telecharges % 10 == 0:
                    print(f"  {telecharges} pages téléchargées ({len(file)} liens en attente) — dernière : {url[-70:]}", flush=True)
                if r.status_code in (403, 429):
                    refus += 1
                    echecs.append((url, r.status_code))
                    if refus >= 5:
                        sys.exit("Le site refuse les requêtes à plusieurs reprises : arrêt. Réessayez plus tard.")
                    continue
                if r.status_code != 200:
                    echecs.append((url, r.status_code))
                    continue
                refus = 0
                contenu = r.content
                if a.action == "telecharger":
                    cache.write_bytes(contenu)
        except requests.RequestException as e:
            echecs.append((url, str(e)[:60]))
            print(f"  échec : {url[-60:]} ({str(e)[:50]})", flush=True)
            continue
        if genre == "pdf":
            texte, titre, date, liens = pdf_vers_texte(contenu), url.rsplit("/", 1)[-1], None, []
        else:
            titre, texte, date, liens = analyser(contenu.decode("utf-8", "replace"))
        for l in liens:
            u = urldefrag(urljoin(url, l.strip()))[0]
            u = re.sub(r"(?:%20|%C2%A0|\s|\xa0)+$", "", u)  # adresses écrites avec une espace finale : 404 sinon
            if u not in vus and url_utile(u):
                if "/demarche/" in u or "/fiche/" in u:
                    file.appendleft(u)  # démarches et fiches pratiques d'abord
                else:
                    file.append(u)
        if len(texte) >= 200:
            resultats.append({"url": url, "titre": titre, "date_maj": date, "type": genre, "texte": texte})

    par_type = Counter(r["type"] for r in resultats)
    par_zone = Counter("/" + urlparse(r["url"]).path.strip("/").split("/")[0] for r in resultats)
    lignes = [f"Pages explorées : {len(vus)} | avec contenu : {len(resultats)} | PDF : {par_type.get('pdf', 0)} | échecs : {len(echecs)}",
              "Zones du site : " + ", ".join(f"{k} {v}" for k, v in par_zone.most_common()),
              f"Caractères au total : {sum(len(r['texte']) for r in resultats)}", "",
              "Exemples (titre | taille | date) :"]
    lignes += [f"  {r['titre'][:80]} | {len(r['texte'])} | {r['date_maj']} | {r['url']}" for r in resultats[:25]]
    if echecs:
        lignes += ["", "Échecs :"] + [f"  {u} | {c}" for u, c in echecs[:30]]
    if file and len(vus) >= a.max:
        lignes.append(f"\nLimite de {a.max} pages atteinte, {len(file)} liens restent à explorer (relancez avec --max plus grand).")
    texte_ctrl = "\n".join(lignes)
    (DOSSIER / "controle_site_douane.txt").write_text(texte_ctrl, encoding="utf-8")
    print(texte_ctrl)
    if a.action == "telecharger":
        with SORTIE.open("w", encoding="utf-8") as f:
            for r in resultats:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n{len(resultats)} pages écrites dans {SORTIE}")


if __name__ == "__main__":
    main()
