#!/usr/bin/env python3
"""
Récupération des textes de l'Union européenne sur les douanes (EUR-Lex / Office des publications).

Utilisation :  python ingestion_eurlex.py
Résultats dans  donnees\\eurlex\\ :
   <CELEX>.html        texte brut tel que diffusé (version française)
   <CELEX>.json        texte découpé en articles (utilisable par la suite)
   resume_eurlex.json  récapitulatif (statut, nombre d'articles)

Aucune clé n'est nécessaire (accès public). Reprise possible : un texte déjà
téléchargé n'est pas retéléchargé (supprimez le fichier pour le forcer).
"""

import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import requests

DOSSIER = Path("donnees") / "eurlex"

# Textes de base (versions telles que publiées au Journal officiel de l'UE).
TEXTES = {
    "32013R0952": "Règlement (UE) n° 952/2013 — code des douanes de l'Union",
    "32015R2446": "Règlement délégué (UE) 2015/2446 — compléments au code des douanes de l'Union",
    "32015R2447": "Règlement d'exécution (UE) 2015/2447 — modalités d'application du code",
    "32016R0341": "Règlement délégué (UE) 2016/341 — dispositions transitoires",
    # Nouveau code (réforme douanière), signalé comme publié le 19 septembre 2026 (source secondaire :
    # numéro à confirmer ; si le téléchargement échoue, c'est que le numéro ou la mise en ligne diffère).
    # Transferts de déchets (met en œuvre la Convention de Bâle ; remplace le règlement (CE) n° 1013/2006).
    "32024R1157": "Règlement (UE) 2024/1157 — transferts de déchets",
    "32026R2108": "Règlement (UE) 2026/2108 — nouveau code des douanes de l'Union et Autorité douanière de l'UE",
}

URLS = [
    # 1) service de l'Office des publications (négociation de contenu)
    ("https://publications.europa.eu/resource/celex/{celex}",
     {"Accept": "application/xhtml+xml, text/html;q=0.9", "Accept-Language": "fra"}),
    # 2) repli : page EUR-Lex
    ("https://eur-lex.europa.eu/legal-content/FR/TXT/HTML/?uri=CELEX:{celex}",
     {"Accept": "text/html", "Accept-Language": "fr"}),
]


class Texte(HTMLParser):
    """Extrait le texte visible d'une page HTML, ligne par ligne."""

    def __init__(self):
        super().__init__()
        self.lignes, self.tampon, self.ignorer = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignorer += 1
        if tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self._fin_ligne()

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignorer = max(0, self.ignorer - 1)
        if tag in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self._fin_ligne()

    def handle_data(self, data):
        if not self.ignorer:
            self.tampon.append(data)

    def _fin_ligne(self):
        ligne = re.sub(r"\s+", " ", "".join(self.tampon).replace("\xa0", " ")).strip()
        if ligne:
            self.lignes.append(ligne)
        self.tampon = []

    def fin(self):
        self._fin_ligne()
        return self.lignes


def decouper_en_articles(lignes):
    """Découpe le corps du texte en articles ; renvoie (préambule, articles, annexes).

    - une ligne « Article 12 » / « Article premier » ouvre un article ;
    - le corps s'arrête à la signature (« Fait à Bruxelles ») : ce qui suit (annexes,
      tableaux de correspondance) est rangé à part ;
    - un article n'est accepté que s'il suit la numérotation (même numéro avec suffixe
      bis/ter, ou numéro suivant, avec une tolérance de 5 vers l'avant), ce qui écarte les
      articles cités à l'intérieur d'articles modificatifs.
    """
    motif = re.compile(
        r"^Article\s+(\d+(?:er)?|premier)(\s*(?:bis|ter|quater|quinquies|sexies|[a-z]))?\s*$",
        re.IGNORECASE)
    # Coquille constatée dans le règlement 2026/2108 : « Section 245 » pour « Article 245 ».
    # On l'accepte comme article seulement si c'est exactement le numéro attendu (et si on est
    # déjà avancé dans le texte, pour ne pas confondre avec une vraie section) ; l'article est signalé.
    motif_section = re.compile(r"^Section\s+(\d+)\s*$", re.IGNORECASE)
    fin = next((i for i, l in enumerate(lignes) if re.match(r"^Fait à ", l)), len(lignes))
    corps, annexes = lignes[:fin], lignes[fin:]

    def numero(m):
        base = m.group(1).lower()
        base = "1" if base in ("premier", "1er") else base
        suffixe = ((m.group(2) if m.lastindex and m.lastindex >= 2 else "") or "").strip().lower()
        return (base + " " + suffixe).strip(), int(base)

    articles, courant, preambule, dernier = [], None, [], 0
    i = 0
    while i < len(corps):
        m = motif.match(corps[i])
        accepte = False
        anomalie = None
        if not m:
            ms = motif_section.match(corps[i])
            if ms and dernier >= 100 and int(ms.group(1)) == dernier + 1:
                m, anomalie = ms, "intitulé « Section %s » dans le texte téléchargé (lu comme article %s)" % (
                    ms.group(1), ms.group(1))
        if m:
            num, valeur = numero(m)
            suffixe = bool(m.lastindex and m.lastindex >= 2 and m.group(2))
            accepte = (valeur == dernier and suffixe) or (dernier < valeur <= dernier + 5)
        if accepte:
            if courant:
                articles.append(courant)
            dernier = valeur
            titre = corps[i + 1] if i + 1 < len(corps) and len(corps[i + 1]) < 160 \
                and not motif.match(corps[i + 1]) else ""
            courant = {"numero": num, "titre": titre, "texte": []}
            if anomalie:
                courant["anomalie_source"] = anomalie
            i += 2 if titre else 1
            continue
        (courant["texte"] if courant else preambule).append(corps[i])
        i += 1
    if courant:
        articles.append(courant)
    for a in articles:
        a["texte"] = "\n".join(a["texte"])
    return preambule, articles, annexes


def telecharger(celex):
    derniere = "aucune réponse"
    for modele, entetes in URLS:
        url = modele.format(celex=celex)
        for essai in range(3):
            try:
                r = requests.get(url, headers={**entetes, "User-Agent": "ia-juridique-prototype/0.1"},
                                 timeout=90, allow_redirects=True)
            except requests.RequestException as e:
                derniere = f"{url} : {e}"
                time.sleep(3)
                continue
            if r.status_code == 200 and len(r.content) > 20000 and b"Article" in r.content:
                return r.content, url
            derniere = f"{url} : code {r.status_code}, {len(r.content)} octets"
            if r.status_code in (200, 202, 429, 500, 502, 503):
                time.sleep(5)
                continue
            break
    return None, derniere


def main():
    DOSSIER.mkdir(parents=True, exist_ok=True)
    bilan = {}
    for celex, intitule in TEXTES.items():
        brut = DOSSIER / f"{celex}.html"
        print(f"{celex} — {intitule}")
        if brut.exists() and brut.stat().st_size > 20000:
            contenu, source = brut.read_bytes(), "fichier déjà présent"
        else:
            contenu, source = telecharger(celex)
            if contenu is None:
                print(f"   ÉCHEC : {source}")
                bilan[celex] = {"intitule": intitule, "statut": "échec", "détail": source}
                continue
            brut.write_bytes(contenu)
        analyseur = Texte()
        analyseur.feed(contenu.decode("utf-8", errors="replace"))
        preambule, articles, annexes = decouper_en_articles(analyseur.fin())
        (DOSSIER / f"{celex}.json").write_text(json.dumps(
            {"celex": celex, "intitule": intitule, "source": source,
             "preambule": "\n".join(preambule), "articles": articles,
             "annexes": "\n".join(annexes)},
            ensure_ascii=False, indent=1), encoding="utf-8")
        longueur = sum(len(a["texte"]) for a in articles)
        print(f"   ok : {len(articles)} articles, {longueur} caractères "
              f"(premier : {articles[0]['numero'] if articles else '—'}, "
              f"dernier : {articles[-1]['numero'] if articles else '—'})")
        bilan[celex] = {"intitule": intitule, "statut": "ok", "articles": len(articles),
                        "caracteres": longueur, "source": source}
    (DOSSIER / "resume_eurlex.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nCopiez-collez ce résultat à Claude.")


if __name__ == "__main__":
    sys.exit(main())
