#!/usr/bin/env python3
"""
Prototype d'ingestion - IA juridique (droit des douanes)

Ce script :
  1. s'authentifie auprès de PISTE (OAuth2, client_credentials) ;
  2. récupère le code des douanes depuis Légifrance (table des matières + articles) ;
  3. récupère un échantillon d'arrêts de la Cour de cassation (chambres commerciale
     et criminelle) depuis Judilibre ;
  4. teste la couverture réelle de Judilibre pour les cours d'appel et les
     tribunaux, en particulier en matière pénale.

Configuration par variables d'environnement (ne JAMAIS écrire le secret dans le code) :
  PISTE_CLIENT_ID       identifiant client de l'application PISTE
  PISTE_CLIENT_SECRET   secret client
  PISTE_ENV             "sandbox" (défaut) ou "production"
  JUDILIBRE_KEYID       (optionnel) clé KeyId si vous préférez cette méthode à OAuth

Utilisation :
  python3 prototype_ingestion.py codes       # liste les codes douanes (ancien et nouveau)
  python3 prototype_ingestion.py code        # ANCIEN code (au 30 avril 2026) + NOUVEAU code
  python3 prototype_ingestion.py code ID DATE  # une version précise (ex. ID 2026-06-01)
  python3 prototype_ingestion.py concordance # liens ancien -> nouveau code (après 'code')
  python3 prototype_ingestion.py jurisprudence [cassation|ca|tj]  # décisions douanières (reprise possible)
  python3 prototype_ingestion.py judilibre   # échantillon Cour de cassation
  python3 prototype_ingestion.py couverture  # test de couverture Judilibre
  python3 prototype_ingestion.py penal       # recherche de décisions pénales douanières
  python3 prototype_ingestion.py tout

Les résultats sont écrits dans le dossier ./donnees/

IMPORTANT : ce script n'a pas pu être testé contre les API réelles (elles ne sont pas
accessibles depuis l'environnement où il a été écrit). Les chemins et paramètres
reposent sur la documentation publique ; au premier lancement, des ajustements
mineurs peuvent être nécessaires (voir la documentation Swagger sur PISTE).
"""

import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

ENV = os.environ.get("PISTE_ENV", "sandbox").lower()

if ENV == "production":
    OAUTH_URL = "https://oauth.piste.gouv.fr/api/oauth/token"
    LEGIFRANCE_BASE = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"
    JUDILIBRE_BASE = "https://api.piste.gouv.fr/cassation/judilibre/v1.0"
else:
    OAUTH_URL = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
    LEGIFRANCE_BASE = "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app"
    JUDILIBRE_BASE = "https://sandbox-api.piste.gouv.fr/cassation/judilibre/v1.0"

# Identifiant Légifrance du code des douanes
CODE_DOUANES_ID = "LEGITEXT000006071570"

# Cadence : 10 appels/s, soit la moitié du plafond de 20 appels/s affiché sur PISTE
MAX_REQ_PAR_SECONDE = 10

DOSSIER_SORTIE = Path("donnees")


# ----------------------------------------------------------------------------
# Outils communs
# ----------------------------------------------------------------------------

class Limiteur:
    """Espace les appels pour rester sous le quota par seconde."""

    def __init__(self, par_seconde):
        self.intervalle = 1.0 / par_seconde
        self.dernier = 0.0

    def attendre(self):
        maintenant = time.monotonic()
        reste = self.intervalle - (maintenant - self.dernier)
        if reste > 0:
            time.sleep(reste)
        self.dernier = time.monotonic()


limiteur = Limiteur(MAX_REQ_PAR_SECONDE)
session = requests.Session()
_jeton = {"valeur": None, "expire": 0.0}


def obtenir_jeton():
    """Récupère (ou renouvelle) le jeton OAuth2."""
    if _jeton["valeur"] and time.time() < _jeton["expire"] - 60:
        return _jeton["valeur"]

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("Variables PISTE_CLIENT_ID et PISTE_CLIENT_SECRET manquantes.")

    rep = session.post(
        OAUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "openid",
        },
        timeout=30,
    )
    if rep.status_code != 200:
        sys.exit(f"Échec d'authentification PISTE ({rep.status_code}) : {rep.text[:300]}")

    corps = rep.json()
    _jeton["valeur"] = corps["access_token"]
    _jeton["expire"] = time.time() + int(corps.get("expires_in", 3600))
    return _jeton["valeur"]


def appeler(methode, url, **kwargs):
    """Appel HTTP avec cadence, authentification et nouvelles tentatives."""
    headers = kwargs.pop("headers", {})
    for tentative in range(5):
        limiteur.attendre()
        headers["Authorization"] = f"Bearer {obtenir_jeton()}"
        keyid = os.environ.get("JUDILIBRE_KEYID")
        if keyid and "judilibre" in url:
            headers["KeyId"] = keyid
        rep = session.request(methode, url, headers=headers, timeout=60, **kwargs)

        if rep.status_code == 429:  # quota dépassé : on patiente
            attente = int(rep.headers.get("Retry-After", 2 ** tentative))
            print(f"  quota atteint, pause de {attente}s")
            time.sleep(attente)
            continue
        if rep.status_code == 401:  # jeton expiré
            _jeton["valeur"] = None
            continue
        if rep.status_code >= 500:
            time.sleep(2 ** tentative)
            continue
        return rep
    return rep


def sauver(nom, contenu):
    DOSSIER_SORTIE.mkdir(exist_ok=True)
    chemin = DOSSIER_SORTIE / nom
    chemin.write_text(json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  écrit : {chemin}")


# ----------------------------------------------------------------------------
# 1. Légifrance : code des douanes
# ----------------------------------------------------------------------------

def iso_date(valeur):
    """Convertit un horodatage en millisecondes (format de l'API) en AAAA-MM-JJ."""
    if isinstance(valeur, (int, float)) and valeur > 10 ** 11:
        return datetime.fromtimestamp(valeur / 1000, tz=timezone.utc).date().isoformat()
    return valeur


def a_du_contenu(x):
    """Vrai si la réponse contient au moins une valeur non vide."""
    if isinstance(x, dict):
        return any(a_du_contenu(v) for v in x.values())
    if isinstance(x, list):
        return any(a_du_contenu(v) for v in x)
    return x not in (None, "", 0, False)


def lister_articles(noeud, chemin=""):
    """Parcourt la table des matières et renvoie la liste des articles."""
    articles = []
    titre = noeud.get("title") or noeud.get("titre") or ""
    chemin_noeud = f"{chemin} > {titre}".strip(" >") if titre else chemin

    for art in noeud.get("articles") or []:
        articles.append({
            "id": art.get("id"),
            "num": art.get("num"),
            "etat": art.get("etat"),
            "chemin": chemin_noeud,
        })
    for sous in noeud.get("sections") or []:
        articles.extend(lister_articles(sous, chemin_noeud))
    return articles


def lister_codes():
    """Liste les codes dont le titre contient 'douane' (ancien et nouveau code)."""
    print("Légifrance : recherche des codes 'douanes'")
    corps = {
        "codeName": "douanes",
        "pageNumber": 1,
        "pageSize": 50,
        "sort": "TITLE_ASC",
        "states": ["VIGUEUR", "ABROGE", "VIGUEUR_DIFF", "ABROGE_DIFF"],
    }
    rep = appeler("POST", LEGIFRANCE_BASE + "/list/code", json=corps)
    if rep.status_code != 200:
        sys.exit(f"Liste des codes inaccessible ({rep.status_code}) : {rep.text[:300]}")
    donnees = rep.json()
    sauver("liste_codes_douanes.json", donnees)
    for code in donnees.get("results", []):
        print(f"  {code.get('id')} | {code.get('titre') or code.get('title')} | "
              f"état : {code.get('etat')} | "
              f"du {code.get('dateDebutVersion') or code.get('dateDebut')} "
              f"au {code.get('dateFinVersion') or code.get('dateFin')}")
    return donnees.get("results", [])


def recuperer_les_deux_codes():
    """Ancien code (au 30 avril 2026) puis nouveau code (état actuel).

    Sur Légifrance, le code des douanes garde le même identifiant : la recodification
    du 1er mai 2026 apparaît comme une nouvelle version datée du même code.
    """
    print("=== Ancien code des douanes (faits antérieurs au 1er mai 2026) ===")
    recuperer_code_douanes(CODE_DOUANES_ID, "2026-04-30", "ancien")
    print("=== Nouveau code des douanes (en vigueur depuis le 1er mai 2026) ===")
    recuperer_code_douanes(CODE_DOUANES_ID, date.today().isoformat(), "nouveau")


def recuperer_code_douanes(text_id=CODE_DOUANES_ID, date_ref=None, etiquette="ancien"):
    """Télécharge un code tel qu'il était en vigueur à date_ref (aujourd'hui par défaut)."""
    print(f"Légifrance : table des matières de {text_id} ({etiquette})")
    date_ref = date_ref or date.today().isoformat()
    print(f"  état du code à la date du {date_ref}")
    corps = {"textId": text_id, "date": date_ref, "nature": "CODE"}

    rep = None
    for chemin in ("/consult/code/tableMatieres", "/consult/legi/tableMatieres"):
        rep = appeler("POST", LEGIFRANCE_BASE + chemin, json=corps)
        if rep.status_code == 200:
            break
    if rep is None or rep.status_code != 200:
        sys.exit(f"Table des matières inaccessible ({rep.status_code}) : {rep.text[:300]}")

    table = rep.json()
    sauver(f"code_douanes_{etiquette}_table_matieres.json", table)

    articles = lister_articles(table)
    print(f"  {len(articles)} articles repérés")
    exemples = ", ".join(str(a.get("num")) for a in articles[:6])
    print(f"  premiers numéros : {exemples}")
    etats = {}
    for a in articles:
        etats[a.get("etat")] = etats.get(a.get("etat"), 0) + 1
    print(f"  états : {etats}")

    # On ne garde que les articles en vigueur pour ce premier passage
    # (la gestion des versions historiques sera traitée ensuite).
    en_vigueur = [a for a in articles if (a.get("etat") or "").upper().startswith("VIGUEUR")]
    cibles = en_vigueur or articles
    print(f"  {len(cibles)} articles à télécharger")

    textes = []
    for i, art in enumerate(cibles, 1):
        rep = appeler("POST", LEGIFRANCE_BASE + "/consult/getArticle", json={"id": art["id"]})
        if rep.status_code != 200:
            print(f"  échec {art['id']} ({rep.status_code})")
            continue
        detail = rep.json().get("article", {})
        textes.append({
            "id": art["id"],
            "num": detail.get("num") or art["num"],
            "chemin": art["chemin"],
            "etat": detail.get("etat"),
            "date_debut": iso_date(detail.get("dateDebut")),
            "date_fin": iso_date(detail.get("dateFin")),
            "texte": detail.get("texte") or detail.get("texteHtml"),
        })
        if i % 100 == 0:
            print(f"  {i}/{len(cibles)}")

    sauver(f"code_douanes_{etiquette}_articles.json", textes)
    print(f"  terminé : {len(textes)} articles enregistrés")


# ----------------------------------------------------------------------------
# 2. Judilibre : échantillon Cour de cassation
# ----------------------------------------------------------------------------

def recuperer_concordance():
    """Interroge Légifrance pour les liens de concordance de chaque ancien article.

    Les réponses sont enregistrées brutes (concordance_brute.json) : on regardera leur
    format avant de construire la table de correspondance ancien -> nouveau.
    """
    print("Légifrance : liens de concordance (ancien code -> nouveau code)")
    chemin_ancien = DOSSIER_SORTIE / "code_douanes_ancien_articles.json"
    if not chemin_ancien.exists():
        print("  fichier de l'ancien code absent : lancez d'abord la commande 'code'")
        return
    anciens = json.loads(chemin_ancien.read_text(encoding="utf-8"))

    def interroger(article_id):
        erreur = None
        for cle in ("articleId", "id"):
            rep = appeler("POST", LEGIFRANCE_BASE + "/consult/concordanceLinksArticle",
                          json={cle: article_id})
            if rep.status_code == 200:
                return rep.json(), None
            erreur = f"{rep.status_code} : {rep.text[:300]}"
        return None, erreur

    resultats = []
    for i, art in enumerate(anciens, 1):
        reponse, erreur = interroger(art["id"])
        if i == 1 and erreur:
            print(f"  l'appel échoue : {erreur}")
            print("  Envoyez ce message à Claude : l'appel ou ses paramètres sont à ajuster.")
            return
        resultats.append({"id": art["id"], "num": art.get("num"),
                          "reponse": reponse, "erreur": erreur})
        if i % 100 == 0:
            print(f"  {i}/{len(anciens)}")

    sauver("concordance_brute.json", resultats)
    avec_contenu = [r for r in resultats if a_du_contenu(r["reponse"])]
    en_erreur = [r for r in resultats if r["erreur"]]
    print(f"  {len(avec_contenu)} articles avec une réponse non vide sur {len(resultats)} "
          f"({len(en_erreur)} erreurs)")
    for r in avec_contenu[:3]:
        print(f"   art. {r['num']} : {json.dumps(r['reponse'], ensure_ascii=False)[:300]}")


def rechercher_judilibre(parametres):
    rep = appeler("GET", JUDILIBRE_BASE + "/search", params=parametres)
    if rep.status_code != 200:
        print(f"  recherche en échec ({rep.status_code}) : {rep.text[:300]}")
        return None
    return rep.json()


def recuperer_echantillon_cassation(nb_par_chambre=50):
    print("Judilibre : échantillon Cour de cassation")
    # cr = chambre criminelle, comm = chambre commerciale
    for chambre in ("cr", "comm"):
        print(f"  chambre {chambre}")
        resultat = rechercher_judilibre({
            "query": "code des douanes",
            "operator": "exact",
            "jurisdiction": "cc",
            "chamber": chambre,
            "page_size": nb_par_chambre,
            "page": 0,
            "resolve_references": "true",
        })
        if not resultat:
            continue

        print(f"    {resultat.get('total', '?')} décisions correspondantes")
        decisions = []
        for item in resultat.get("results", []):
            rep = appeler("GET", JUDILIBRE_BASE + "/decision", params={"id": item["id"]})
            if rep.status_code == 200:
                decisions.append(rep.json())
        sauver(f"judilibre_cassation_{chambre}.json", decisions)


# ----------------------------------------------------------------------------
# 3. Judilibre : test de couverture (cours d'appel, tribunaux, pénal)
# ----------------------------------------------------------------------------

def recuperer_jurisprudence(perimetre="cassation", compter=False):
    """Télécharge les décisions judiciaires qui mentionnent le droit des douanes.

    Périmètres : cassation (chambres criminelle et commerciale), ca (cours d'appel),
    tj (tribunaux judiciaires). Les décisions sont enregistrées au fil de l'eau dans
    donnees/jurisprudence_<périmètre>.jsonl ; le script peut être relancé après une
    interruption : il reprend sans retélécharger.
    """
    perimetres = {
        "cassation": ([("cc", "cr"), ("cc", "comm")], 1990),
        "ca": ([("ca", None)], 2015),
        "tj": ([("tj", None)], 2023),
    }
    if perimetre not in perimetres:
        sys.exit("Périmètre inconnu : choisissez cassation, ca ou tj.")
    cibles, annee_debut = perimetres[perimetre]
    expressions = ["code des douanes", "administration des douanes"]

    DOSSIER_SORTIE.mkdir(exist_ok=True)
    fichier = DOSSIER_SORTIE / f"jurisprudence_{perimetre}.jsonl"
    deja = set()
    if fichier.exists():
        for ligne in fichier.read_text(encoding="utf-8").splitlines():
            if ligne.strip():
                try:
                    deja.add(json.loads(ligne).get("id"))
                except ValueError:
                    pass
        print(f"  reprise : {len(deja)} décisions déjà enregistrées")

    print(f"Judilibre : jurisprudence douanière ({perimetre}) depuis {annee_debut}")
    nouvelles = 0
    echecs = 0
    with fichier.open("a", encoding="utf-8") as sortie:
        for juridiction, chambre in cibles:
            libelle = f"{juridiction}/{chambre or 'toutes chambres'}"
            for annee in range(annee_debut, date.today().year + 1):
                trouvees = {}
                for expression in expressions:
                    page = 0
                    while True:
                        params = {
                            "query": expression,
                            "operator": "exact",
                            "jurisdiction": juridiction,
                            "date_start": f"{annee}-01-01",
                            "date_end": f"{annee}-12-31",
                            "page_size": 50,
                            "page": page,
                        }
                        if chambre:
                            params["chamber"] = chambre
                        resultat = rechercher_judilibre(params)
                        if not resultat:
                            break
                        for r in resultat.get("results", []):
                            trouvees[r["id"]] = r
                        page += 1
                        if page * 50 >= resultat.get("total", 0) or page >= 199:
                            break
                a_telecharger = [] if compter else [i for i in trouvees if i not in deja]
                for ident in a_telecharger:
                    rep = appeler("GET", JUDILIBRE_BASE + "/decision", params={"id": ident})
                    if rep.status_code != 200:
                        echecs += 1
                        print(f"    échec {ident} ({rep.status_code})")
                        continue
                    sortie.write(json.dumps(rep.json(), ensure_ascii=False) + "\n")
                    sortie.flush()
                    deja.add(ident)
                    nouvelles += 1
                if trouvees:
                    print(f"  {libelle} {annee} : {len(trouvees)} décisions, {len(a_telecharger)} nouvelles")
    print(f"  terminé : {nouvelles} nouvelles décisions, {len(deja)} au total, {echecs} échecs")
    print(f"  fichier : {fichier}")


def tester_couverture():
    print("Judilibre : test de couverture")
    tests = [
        ("Cour de cassation - chambre criminelle", {"jurisdiction": "cc", "chamber": "cr"}),
        ("Cour de cassation - chambre commerciale", {"jurisdiction": "cc", "chamber": "comm"}),
        ("Cours d'appel", {"jurisdiction": "ca"}),
        ("Tribunaux judiciaires", {"jurisdiction": "tj"}),
    ]
    rapport = []
    for libelle, filtres in tests:
        # La 3e requête est un témoin : elle doit renvoyer 0. Sinon, la recherche
        # ne filtre pas et les totaux ne veulent rien dire.
        for requete in ("code des douanes", "contrebande", "zzqxwvk"):
            resultat = rechercher_judilibre({
                **filtres,
                "query": requete,
                "operator": "exact",
                "date_start": "2025-01-01",
                "page_size": 5,
            })
            total = resultat.get("total") if resultat else None
            exemples = []
            if resultat:
                for r in resultat.get("results", [])[:3]:
                    exemples.append({
                        "id": r.get("id"),
                        "date": r.get("decision_date"),
                        "juridiction": r.get("jurisdiction"),
                        "formation": r.get("chamber"),
                        "type": r.get("type"),
                        "themes": r.get("themes"),
                        "resume": (r.get("summary") or "")[:200],
                    })
            print(f"  {libelle} | '{requete}' | depuis 2025 : {total}")
            rapport.append({
                "perimetre": libelle,
                "requete": requete,
                "total_depuis_2025": total,
                "exemples": exemples,
            })
    sauver("judilibre_couverture.json", rapport)
    print("  Contrôle : la requête 'zzqxwvk' doit donner 0. Sinon, le filtre ne fonctionne pas.")
    print("  Regardez 'type' et 'themes' dans le fichier pour repérer les décisions pénales.")


def tester_penal():
    print("Judilibre : recherche de décisions pénales douanières (cours d'appel, tribunaux)")
    recherches = [
        ("article 414 (contrebande)", "article 414 du code des douanes", "exact"),
        ("douanes + correctionnel + prévenu", "douanes correctionnel prévenu", "and"),
        ("douanes + correctionnel + condamné", "douanes correctionnel condamné", "and"),
    ]
    rapport = []
    for juridiction, nom in (("ca", "Cours d'appel"), ("tj", "Tribunaux judiciaires")):
        for libelle, requete, operateur in recherches:
            resultat = rechercher_judilibre({
                "query": requete,
                "operator": operateur,
                "jurisdiction": juridiction,
                "date_start": "2025-01-01",
                "page_size": 10,
            })
            total = resultat.get("total") if resultat else None
            print(f"  {nom} | {libelle} | depuis 2025 : {total}")
            exemples = []
            for r in (resultat or {}).get("results", []):
                exemples.append({
                    "id": r.get("id"),
                    "date": r.get("decision_date"),
                    "formation": r.get("chamber"),
                    "type": r.get("type"),
                    "themes": r.get("themes"),
                })
                print(f"      {r.get('decision_date')} | {r.get('chamber')} | {r.get('type')}")
            rapport.append({
                "perimetre": nom,
                "recherche": libelle,
                "requete": requete,
                "operateur": operateur,
                "total_depuis_2025": total,
                "exemples": exemples,
            })
    sauver("judilibre_penal.json", rapport)


# ----------------------------------------------------------------------------

if __name__ == "__main__":
    commande = sys.argv[1] if len(sys.argv) > 1 else "tout"
    print(f"Environnement PISTE : {ENV}")
    if commande == "codes":
        lister_codes()
    if commande in ("code", "tout"):
        if commande == "code" and len(sys.argv) > 2:
            # python prototype_ingestion.py code IDENTIFIANT [AAAA-MM-JJ] : un code précis
            text_id = sys.argv[2]
            date_ref = sys.argv[3] if len(sys.argv) > 3 else date.today().isoformat()
            etiquette = "ancien" if date_ref < "2026-05-01" else "nouveau"
            recuperer_code_douanes(text_id, date_ref, etiquette)
        else:
            recuperer_les_deux_codes()
    if commande == "jurisprudence":
        # python prototype_ingestion.py jurisprudence [cassation|ca|tj]
        recuperer_jurisprudence(sys.argv[2] if len(sys.argv) > 2 else "cassation", compter=(len(sys.argv) > 3 and sys.argv[3] == "compter"))
    if commande in ("concordance", "tout"):
        recuperer_concordance()
    if commande in ("judilibre", "tout"):
        recuperer_echantillon_cassation()
    if commande in ("couverture", "tout"):
        tester_couverture()
    if commande in ("penal", "tout"):
        tester_penal()
    if commande not in ("codes", "code", "concordance", "jurisprudence", "judilibre", "couverture", "penal", "tout"):
        sys.exit(__doc__)
