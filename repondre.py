#!/usr/bin/env python3
"""
Réponse rédigée à une question juridique, à partir des seuls passages retrouvés dans le corpus, avec vérification
automatique des citations. PROTOTYPE : les réponses doivent être relues par un juriste avant tout usage.

Prérequis : une clé d'API dans une variable d'environnement (jamais dans un fichier ni dans une conversation) :
    set MISTRAL_API_KEY=votre_clé          (invite de commandes Windows, valable pour la fenêtre en cours)
Le corpus est public : seuls la question et les passages publics retrouvés sont envoyés au service d'IA.
N'y écrivez AUCUNE donnée interne ou nominative.

Utilisation :
   python repondre.py "Quelles sont les causes de nullité d'un procès-verbal de saisie ?" --faits 2025-03-01
   python repondre.py "..." --simuler          # sans appel réseau (test du fonctionnement et du vérificateur)
   python repondre.py "..." --modele mistral-large-latest
Options : --faits AAAA-MM-JJ   --modele NOM   --n NOMBRE (décisions de jurisprudence, défaut 6)   --base CHEMIN
Variables facultatives : MISTRAL_API_KEY, API_URL (défaut https://api.mistral.ai/v1/chat/completions), MODELE
Écrit : journal_reponses.jsonl (question, passages envoyés, réponse, résultat de la vérification)
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import chercher

API_URL = os.environ.get("API_URL", "https://api.mistral.ai/v1/chat/completions")
MODELE_DEFAUT = os.environ.get("MODELE", "mistral-large-latest")
MAX_CAR_PASSAGE = 1800

CONSIGNES = """Tu es un assistant juridique spécialisé en droit douanier français, au service d'agents de l'administration des douanes. \
Tu réponds en français, de façon structurée et prudente.

RÈGLES ABSOLUES
1. Tu t'appuies UNIQUEMENT sur les passages numérotés [1], [2]… fournis ci-dessous. Tu n'utilises aucune autre connaissance juridique, \
même si tu crois la connaître. Si les passages ne permettent pas de répondre, ou seulement en partie, dis-le explicitement \
(« Les passages fournis ne permettent pas de répondre à… ») et n'invente rien.
2. Chaque affirmation juridique est suivie de la référence du passage qui la fonde, sous la forme [n]. N'écris jamais un numéro d'article, \
un numéro de pourvoi ou une date de décision qui ne figure pas dans les passages.
3. Quand tu cites un texte ou une décision, tu peux reprendre un extrait EXACT entre guillemets français « … », copié mot pour mot d'un passage. \
Ne reformule jamais à l'intérieur de guillemets.
4. Date des faits : chaque passage porte une mention de statut. Respecte-la. Un texte marqué « abrogé » ou « ancien code » n'est applicable \
que si la date des faits l'impose ; un texte du nouveau code n'est pas applicable à des faits antérieurs au 1er mai 2026, sauf règle de \
procédure à vérifier : dans ce cas, signale-le. Si la date des faits n'est pas indiquée et que la réponse en dépend, demande-la ou \
présente les deux hypothèses.
5. Hiérarchie : distingue la loi, la jurisprudence (Cour de cassation, Conseil constitutionnel, Conseil d'État, CJUE), la doctrine \
administrative (BOD) qui n'a pas force de loi. Les pages du site douane.gouv.fr sont des informations pratiques sans valeur de texte légal : présente-les comme telles, avec leur date de mise à jour, et confronte-les aux textes. Les conclusions d'un avocat général ne lient pas la Cour. Une décision ancienne peut avoir \
été dépassée : ne l'affirme pas sans passage qui le dise, mais signale ce risque.
6. Termine par une rubrique « Points à vérifier » (incertitudes, textes manquants, évolutions possibles) et rappelle que la réponse doit être \
relue par un juriste.

FORMAT
- Réponse courte d'abord (2 à 4 phrases), puis analyse détaillée, puis « Points à vérifier ».
- Pas de références en dehors du format [n]."""


def charger_passages(con, question, faits, n_juris, ancien=False, n_par_famille=None):
    groupes = chercher.chercher_groupes(con, question, n_juris, n_par_famille=n_par_famille, source=None, faits=faits, toutes_versions=False, ancien=ancien)
    passages, k = [], 0
    for titre, res in groupes:
        for r in res:
            k += 1
            texte, note = chercher.separer_concordance(r["texte"])
            texte = re.sub(r"\s+", " ", texte).strip()
            if len(texte) > MAX_CAR_PASSAGE:
                texte = texte[:MAX_CAR_PASSAGE] + " […]"
            statut = r["statut_detail"] or ("abrogé" if r["statut"] == "abroge" else "")
            if r["source"] == "code_douanes_nouveau" and faits and faits < chercher.DATE_RECODIFICATION:
                statut = "NOUVEAU CODE, en vigueur depuis le 1er mai 2026 : non applicable aux faits antérieurs (sauf règle de procédure, à vérifier)"
            elif r["source"] == "code_douanes_ancien" and faits and faits < chercher.DATE_RECODIFICATION:
                statut = "ancien code, applicable aux faits antérieurs au 1er mai 2026"
            passages.append({"n": k, "famille": titre, "ref": r["ref"], "date": r["date"], "section": r["section"],
                             "statut": statut, "concordance": note, "texte": texte, "source": r["source"]})
    for s in chercher.sections(con, question, faits, ancien, max_sections=2, max_articles=40 if n_par_famille else 15):
        for art in s["articles"]:
            if any(p["ref"] == art["ref"] for p in passages):
                continue
            k += 1
            texte, note = chercher.separer_concordance(art["texte"])
            texte = re.sub(r"\s+", " ", texte).strip()[:MAX_CAR_PASSAGE]
            passages.append({"n": k, "famille": "Section : " + s["intitule"].split(">")[-1].strip(), "ref": art["ref"],
                             "date": art["date"], "section": "texte", "statut": art["statut_detail"] or "", "concordance": note,
                             "texte": texte, "source": art["source"]})
    return passages


CONSIGNES_TRI = """Tu aides un assistant juridique en droit douanier français. On te donne une QUESTION et une liste numérotée de \
passages candidats (références et début de texte). Tu ne réponds PAS à la question : tu choisis les passages à transmettre \
à l'assistant qui rédigera la réponse.

Étapes :
1. Détermine le type de question : « pratique » (démarches, documents à fournir, formalités : les pages du site \
douane.gouv.fr sont alors souvent les plus utiles, avec les textes qui les fondent), « texte » (quel article, quelle règle), \
« contentieux » (nullités, sanctions, jurisprudence : la jurisprudence et les textes priment, les pages du site sont \
secondaires) ou « valeur » (valeur en douane, origine, classement : le droit de l'Union est central).
2. Retiens au plus {maximum} passages, utiles pour répondre. Retiens tous les articles d'un même ensemble cohérent \
(par exemple une section entière dont l'intitulé correspond à la question). Écarte les passages dont seul un mot \
coïncide avec la question. En cas de doute sur un texte de loi ou de règlement directement applicable, garde-le.

Réponds uniquement par un objet JSON : {{"type": "pratique|texte|contentieux|valeur", "retenus": [numéros des passages \
retenus, du plus utile au moins utile], "motif": "une phrase"}}."""


def reclasser(passages, question, faits, modele_tri, maximum):
    """Demande au modèle de choisir parmi les candidats. Renvoie (retenus, type, motif) ou None si échec."""
    lignes = []
    for p in passages:
        debut = p["texte"][:260]
        lignes.append(f"[{p['n']}] {p['ref']} ({p['famille']}) : {debut}")
    utilisateur = (f"QUESTION : {question}\nDATE DES FAITS : {faits or 'non précisée'}\n\nPASSAGES CANDIDATS :\n\n"
                   + "\n".join(lignes))
    try:
        brut = appeler_api([{"role": "system", "content": CONSIGNES_TRI.format(maximum=maximum)},
                            {"role": "user", "content": utilisateur}], modele_tri, json_mode=True)
        m = re.search(r"\{.*\}", brut, re.S)
        d = json.loads(m.group(0))
        valides = {p["n"] for p in passages}
        ids = []
        for x in d.get("retenus", []):
            try:
                x = int(x)
            except (TypeError, ValueError):
                continue
            if x in valides and x not in ids:
                ids.append(x)
        if not ids:
            return None
        return ids[:maximum], str(d.get("type", "")), str(d.get("motif", ""))
    except (ValueError, KeyError, AttributeError, TypeError):
        return None


def construire_messages(question, faits, passages):
    blocs = []
    for p in passages:
        en_tete = f"[{p['n']}] {p['ref']} — {p['famille']}"
        if p["date"]:
            en_tete += f" — {p['date']}"
        if p["statut"]:
            en_tete += f" — STATUT : {p['statut']}"
        corps = p["texte"] + (f"\n(Concordance : {p['concordance']})" if p["concordance"] else "")
        blocs.append(en_tete + "\n" + corps)
    contexte = "\n\n".join(blocs) if blocs else "(aucun passage trouvé)"
    utilisateur = (f"QUESTION : {question}\nDATE DES FAITS : {faits or 'non précisée'}\n\n"
                   f"PASSAGES DISPONIBLES :\n\n{contexte}")
    return [{"role": "system", "content": CONSIGNES}, {"role": "user", "content": utilisateur}]


def appeler_api(messages, modele, json_mode=False):
    cle = os.environ.get("MISTRAL_API_KEY")
    if not cle:
        sys.exit("Variable MISTRAL_API_KEY absente. Dans l'invite de commandes :  set MISTRAL_API_KEY=votre_clé  "
                 "(puis relancez ; ne collez jamais la clé dans une conversation).")
    demande = {"model": modele, "messages": messages, "temperature": 0.1}
    if json_mode:
        demande["response_format"] = {"type": "json_object"}
    corps = json.dumps(demande).encode("utf-8")
    for essai in range(4):
        req = urllib.request.Request(API_URL, data=corps, headers={"Content-Type": "application/json",
                                                                   "Authorization": "Bearer " + cle})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8"))
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503) and essai < 3:
                time.sleep(5 * (essai + 1))
                continue
            sys.exit(f"Erreur de l'API ({e.code}) : {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            if essai < 3:
                time.sleep(5 * (essai + 1))
                continue
            sys.exit(f"API injoignable : {e}")


def reponse_simulee(passages):
    """Réponse de test : une citation exacte, une citation inventée et un numéro de pourvoi inexistant, pour tester le vérificateur."""
    if not passages:
        return "Les passages fournis ne permettent pas de répondre."
    p = passages[0]
    extrait = " ".join(p["texte"].split()[:12])
    return (f"Réponse courte : selon le passage [1], « {extrait} ».\n\n"
            f"Une phrase inventée : « ce texte prévoit expressément une amende de dix mille euros pour tout manquement » [1].\n"
            f"Une citation d'un passage inexistant [99]. Voir aussi Cass. crim., 1er janvier 2000, n° 99-12.345 [1].\n\n"
            f"Points à vérifier : réponse simulée, à relire par un juriste.")


def normaliser(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("’", "'").replace("‑", "-").replace("‐", "-")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


RE_CITATION = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
RE_EXTRAIT = re.compile(r"«\s*([^«»]{25,}?)\s*»")
RE_POURVOI = re.compile(r"\b(\d{2}-\d{2}\.\d{3})\b")
RE_ARTICLE = re.compile(r"\b(?:articles?|art\.)\s+((?:L\.?\s?|R\.?\s?|D\.?\s?)?\d+(?:-\d+)*(?:\s+(?:bis|ter|quater))?)", re.I)


def verifier(reponse, passages):
    """Vérifie automatiquement : (1) tout [n] existe ; (2) tout extrait entre « » figure dans un passage ; (3) tout numéro de
    pourvoi et tout numéro d'article cité figure dans les passages envoyés. Ne vérifie PAS que le raisonnement est juste."""
    valides = {p["n"] for p in passages}
    corpus_norm = normaliser(" ".join(p["ref"] + " " + p["texte"] for p in passages))
    anomalies = []
    cites = set()
    for m in RE_CITATION.finditer(reponse):
        for x in re.split(r"[,;]", m.group(1)):
            n = int(x)
            cites.add(n)
            if n not in valides:
                anomalies.append(f"Renvoi [{n}] vers un passage qui n'existe pas.")
    for m in RE_EXTRAIT.finditer(reponse):
        e = normaliser(m.group(1))
        if e and e not in corpus_norm:
            anomalies.append(f"Extrait entre guillemets introuvable dans les passages : « {m.group(1)[:90]}… »")
    for m in RE_POURVOI.finditer(reponse):
        if normaliser(m.group(1)) not in corpus_norm:
            anomalies.append(f"Numéro de pourvoi {m.group(1)} absent des passages fournis.")
    for m in RE_ARTICLE.finditer(reponse):
        num = normaliser(m.group(1).replace(".", ""))
        if num and num not in corpus_norm:
            anomalies.append(f"Article « {m.group(1)} » absent des passages fournis.")
    if not cites and "ne permettent pas" not in reponse:
        anomalies.append("Aucune citation [n] dans la réponse.")
    return sorted(cites), list(dict.fromkeys(anomalies))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--faits")
    ap.add_argument("--modele", default=MODELE_DEFAUT)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--simuler", action="store_true")
    ap.add_argument("--sans-tri", action="store_true", help="n'utilise pas la sélection par le modèle (passages directs de la recherche)")
    ap.add_argument("--modele-tri", default=None, help="modèle pour la sélection (défaut : le même que pour la réponse)")
    ap.add_argument("--candidats", type=int, default=20, help="candidats par famille soumis à la sélection (défaut 20)")
    ap.add_argument("--retenus", type=int, default=25, help="nombre maximal de passages transmis pour la réponse (défaut 25)")
    ap.add_argument("--ancien", action="store_true", help="inclut aussi l'ancien code des douanes")
    ap.add_argument("--base", default=str(chercher.BASE_DEFAUT))
    a = ap.parse_args()
    if not Path(a.base).exists():
        sys.exit(f"Base introuvable : {a.base}")
    con = sqlite3.connect(a.base)
    tri = None
    utiliser_tri = not a.sans_tri and not a.simuler
    passages = charger_passages(con, a.question, a.faits, a.candidats if utiliser_tri else a.n, a.ancien,
                                n_par_famille=a.candidats if utiliser_tri else None)
    if not passages:
        print("Aucun passage trouvé : pas de réponse possible.")
        return
    if utiliser_tri:
        candidats = len(passages)
        tri = reclasser(passages, a.question, a.faits, a.modele_tri or a.modele, a.retenus)
        if tri:
            ids, type_q, motif = tri
            garde = [p for p in passages if p["n"] in set(ids)]
            for k, p in enumerate(garde, 1):
                p["n"] = k
            passages = garde
            print(f"[Sélection] question de type « {type_q} » : {len(passages)} passages retenus sur {candidats}. {motif}\n")
        else:
            print("[Sélection] échec de la sélection par le modèle : repli sur les passages classés par la recherche.\n")
            passages = charger_passages(con, a.question, a.faits, a.n, a.ancien)
    messages = construire_messages(a.question, a.faits, passages)
    reponse = reponse_simulee(passages) if a.simuler else appeler_api(messages, a.modele)
    cites, anomalies = verifier(reponse, passages)

    print(reponse)
    print("\n" + "─" * 70)
    if anomalies:
        print("⚠ VÉRIFICATION AUTOMATIQUE : " + str(len(anomalies)) + " anomalie(s) à contrôler avant tout usage")
        for x in anomalies:
            print("   - " + x)
    else:
        print("✓ Vérification automatique : renvois, extraits, articles et pourvois cités retrouvés dans les passages "
              "(cela ne garantit pas que le raisonnement soit juste).")
    print("\nSources citées :")
    for p in passages:
        if p["n"] in cites:
            print(f"  [{p['n']}] {p['ref']}" + (f" ({p['date']})" if p["date"] else "")
                  + (f" — {p['statut']}" if p["statut"] else ""))
    non_cites = [p["n"] for p in passages if p["n"] not in cites]
    print(f"\n(Passages fournis au modèle mais non cités : {non_cites or 'aucun'})")
    print("Rappel : prototype, réponse à faire relire par un juriste.")
    with open("journal_reponses.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M:%S"), "question": a.question, "faits": a.faits,
                            "modele": "simulation" if a.simuler else a.modele, "passages": passages,
                            "reponse": reponse, "anomalies": anomalies, "tri": tri}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
