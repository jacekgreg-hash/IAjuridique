#!/usr/bin/env python3
"""
Construction des « passages » : tout le corpus est découpé en petits morceaux homogènes, chacun avec sa référence
citable, sa date, son statut (en vigueur / abrogé / décision...) et un poids de pertinence. C'est la matière de l'index
de recherche. Aucun appel réseau ; les fichiers d'origine ne sont pas modifiés.

Utilisation :   python construire_passages.py
Lit      :  tous les fichiers de donnees\\ (codes, concordances, eurlex, cjue, jurisprudences filtrées, doctrine)
Écrit    :  donnees\\index\\passages.jsonl   donnees\\index\\controle_passages.txt

Une source absente est signalée et ignorée (le script ne s'arrête pas).
"""

import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DONNEES = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("donnees")
SORTIE = DONNEES / "index"
MAX_CAR = 1800
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
CHAMBRES = {"cr": "crim.", "comm": "com.", "pl": "ass. plén.", "mi": "ch. mixte", "civ1": "1re civ.", "civ2": "2e civ.",
            "civ3": "3e civ.", "soc": "soc."}
ORDRE_ZONES = ["introduction", "expose", "moyens", "motivations", "dispositif"]
ETIQUETTE_ZONE = {"introduction": "intro", "expose": "exposé", "moyens": "moyens", "motivations": "motifs",
                  "dispositif": "dispositif"}


# ---------------------------------------------------------------- utilitaires
def lire_jsonl(chemin):
    with chemin.open(encoding="utf-8") as f:
        for ligne in f:
            if ligne.strip():
                try:
                    yield json.loads(ligne)
                except ValueError:
                    continue


def lire_json(chemin):
    return json.loads(chemin.read_text(encoding="utf-8"))


def en_date(v):
    """Dates Légifrance en millisecondes (négatives avant 1970) ou texte AAAA-MM-JJ."""
    if isinstance(v, (int, float)):
        return (datetime(1970, 1, 1) + timedelta(milliseconds=v)).date().isoformat()
    return str(v)[:10] if v else None


def date_fr(iso):
    if not iso or not re.match(r"\d{4}-\d{2}-\d{2}", iso):
        return iso or "date inconnue"
    jour = "1er" if iso[8:10] == "01" else str(int(iso[8:10]))
    return f"{jour} {MOIS[int(iso[5:7]) - 1]} {iso[:4]}"


def decouper(texte, max_car=MAX_CAR):
    """Découpe en morceaux d'au plus ~max_car caractères, aux fins de ligne ; reprend la dernière ligne (courte)."""
    lignes = []
    for l in (texte or "").split("\n"):
        l = l.strip()
        while len(l) > max_car:
            coupe = l.rfind(" ", 0, max_car)
            coupe = coupe if coupe > max_car // 2 else max_car
            lignes.append(l[:coupe])
            l = l[coupe:].lstrip()
        if l:
            lignes.append(l)
    morceaux, courant, taille = [], [], 0
    for l in lignes:
        if courant and taille + len(l) + 1 > max_car:
            morceaux.append("\n".join(courant))
            reprise = courant[-1] if len(courant[-1]) < 400 else None
            courant, taille = ([reprise] if reprise else []), (len(reprise) if reprise else 0)
        courant.append(l)
        taille += len(l) + 1
    if courant:
        reste = "\n".join(courant)
        if not morceaux or len(reste) > 120 or reste not in morceaux[-1]:
            morceaux.append(reste)
    return morceaux


class Collecteur:
    def __init__(self):
        self.f = None
        self.stats = defaultdict(lambda: {"docs": set(), "passages": 0, "car": 0})
        self.exemples = defaultdict(list)
        self.alertes = Counter()

    def __enter__(self):
        SORTIE.mkdir(parents=True, exist_ok=True)
        self.f = (SORTIE / "passages.jsonl").open("w", encoding="utf-8")
        return self

    def __exit__(self, *a):
        self.f.close()

    def ajouter(self, source, famille, doc_id, k, ref, titre, texte, date, statut, poids, statut_detail=None,
                section=None, **meta):
        texte = (texte or "").strip()
        if not texte:
            self.alertes[f"{source} : passage vide ignoré"] += 1
            return
        if not date:
            self.alertes[f"{source} : sans date"] += 1
        p = {"pid": f"{source}:{doc_id}:{k}", "source": source, "famille": famille, "doc_id": str(doc_id),
             "ref": ref, "titre": titre, "section": section, "date": date, "statut": statut,
             "statut_detail": statut_detail, "poids": round(poids, 2), "texte": texte, "meta": meta}
        self.f.write(json.dumps(p, ensure_ascii=False) + "\n")
        s = self.stats[source]
        s["docs"].add(str(doc_id))
        s["passages"] += 1
        s["car"] += len(texte)
        if len(self.exemples[source]) < 2 and (s["passages"] % 97 == 1):
            self.exemples[source].append(p)

    def document(self, source, famille, doc_id, ref, titre, texte, date, statut, poids, **kw):
        for k, morceau in enumerate(decouper(texte)):
            self.ajouter(source, famille, doc_id, k, ref, titre, morceau, date, statut, poids, **kw)


# ---------------------------------------------------------------- codes français
def charger_codes(c):
    conc = lire_json(DONNEES / "concordance_finale.json") if (DONNEES / "concordance_finale.json").exists() else {}
    a2n, n2a = conc.get("ancien_vers_nouveau", {}), conc.get("nouveau_vers_ancien", {})

    def corresp(table, num):
        v = table.get(str(num).strip())
        return json.dumps(v, ensure_ascii=False)[:400] if v else None

    for fichier, source, nom, tab in (("code_douanes_ancien_articles.json", "code_douanes_ancien", "Code des douanes (ancien)", a2n),
                                       ("code_douanes_nouveau_articles.json", "code_douanes_nouveau", "Code des douanes (nouveau)", n2a)):
        chemin = DONNEES / fichier
        if not chemin.exists():
            c.alertes[f"{fichier} absent"] += 1
            continue
        ancien = source.endswith("ancien")
        for a in lire_json(chemin):
            fin = en_date(a.get("date_fin"))
            debut = en_date(a.get("date_debut"))
            ref = f"{nom}, art. {a['num']}"
            if ancien:
                statut = "abroge"
                detail = ("Version applicable aux faits antérieurs au 1er mai 2026 (code recodifié par l'ordonnance "
                          f"n° 2026-265) ; fin de validité : {fin}")
            else:
                statut = "en_vigueur"
                detail = f"En vigueur depuis le {debut}" if debut else None
            texte = a.get("texte") or ""
            corr = corresp(tab, a["num"])
            if corr:
                texte += f"\nCorrespondance ancien/nouveau code (table officielle 2026) : {corr}"
            c.document(source, "legislation", a["id"], ref, f"{ref} — {a.get('chemin', '')[-120:]}", texte, debut,
                       statut, 1.3 if not ancien else 1.2, statut_detail=detail, num=a["num"], date_fin=fin,
                       chemin=a.get("chemin"))
    chemin = DONNEES / "code_cpp_articles.json"
    if chemin.exists():
        for a in lire_json(chemin):
            fin, debut = en_date(a.get("date_fin")), en_date(a.get("date_debut"))
            diff = a.get("etat") == "ABROGE_DIFF"
            detail = (f"En vigueur ; abrogation programmée le {fin} (réécriture du code par l'ordonnance n° 2025-1091)"
                      if diff else None)
            ref = f"Code de procédure pénale, art. {a['num']}"
            c.document("code_cpp", "legislation", a["id"], ref, ref, a.get("texte"), debut, "en_vigueur", 1.1,
                       statut_detail=detail, num=a["num"], fin_prevue=fin if diff else None)
    else:
        c.alertes["code_cpp_articles.json absent"] += 1


# ---------------------------------------------------------------- droit de l'Union
def charger_ue(c):
    conc = DONNEES / "eurlex" / "concordance_ue.json"
    ue = lire_json(conc) if conc.exists() else {}
    statuts = {
        "32013R0952": ("en_vigueur", "Code des douanes de l'Union ; son remplacement par le règlement (UE) 2026/2108 est "
                                      "différé (articles 284 à 287 de ce dernier) — date exacte à confirmer"),
        "32015R2446": ("en_vigueur", "Acte délégué complétant le règlement (UE) n° 952/2013"),
        "32015R2447": ("en_vigueur", "Acte d'exécution du règlement (UE) n° 952/2013"),
        "32016R0341": ("en_vigueur", "Acte transitoire lié au règlement (UE) n° 952/2013"),
        "32024R1157": ("en_vigueur", "Règlement sur les transferts de déchets (met en œuvre la Convention de Bâle) ; "
                                      "remplace le règlement (CE) n° 1013/2006 ; application générale à compter du "
                                      "21 mai 2026 (à confirmer)"),
        "32026R2108": ("adopte_application_differee", "Nouveau code des douanes de l'Union : application différée "
                                                      "(application générale prévue le 21 septembre 2027, à confirmer)"),
    }
    dates = {"32013R0952": "2013-10-09", "32015R2446": "2015-07-28", "32015R2447": "2015-11-24",
             "32016R0341": "2015-12-17", "32024R1157": "2024-04-11"}      # dates de signature
    for chemin in sorted((DONNEES / "eurlex").glob("3*.json")):
        celex = chemin.stem
        d = lire_json(chemin)
        statut, detail = statuts.get(celex, ("en_vigueur", None))
        court = d["intitule"].split(" — ")[0]
        for a in d.get("articles", []):
            ref = f"{court}, art. {a['numero']}"
            texte = a.get("texte") or ""
            corr = None
            if celex == "32013R0952":
                corr = (ue.get("ancien_vers_nouveau") or {}).get(str(a["numero"]))
            elif celex == "32026R2108":
                corr = (ue.get("nouveau_vers_ancien") or {}).get(str(a["numero"]))
            if corr:
                texte += "\nCorrespondance (annexe du règlement 2026/2108) : " + json.dumps(corr, ensure_ascii=False)[:400]
            c.document("ue_" + celex, "droit_ue", f"{celex}-{a['numero']}", ref,
                       f"{d['intitule']} — art. {a['numero']} : {a.get('titre') or ''}", texte, dates.get(celex), statut, 1.2,
                       statut_detail=detail, celex=celex, num=a["numero"])

    # Convention de Bâle (traité international ; texte français, version d'information 2014)
    bale = DONNEES / "bale" / "convention_bale.json"
    if bale.exists():
        d = lire_json(bale)
        detail = ("Traité international (la France y est partie) ; version d'information du Secrétariat de la Convention, "
                  "à jour au 27 mai 2014 : seul fait foi le texte conservé par le Secrétaire général des Nations Unies. "
                  "Mise en œuvre dans l'Union par le règlement (UE) 2024/1157")
        for a in d.get("articles", []):
            c.document("ue_bale", "droit_ue", f"BALE-{a['numero']}", f"Convention de Bâle, art. {a['numero']}",
                       f"{d['intitule']} — art. {a['numero']} : {a.get('titre') or ''}", a["texte"], d.get("date"),
                       "en_vigueur", 1.2, statut_detail=detail, celex="BALE", num=a["numero"])
        for a in d.get("annexes", []):
            c.document("ue_bale", "droit_ue", f"BALE-ANNEXE-{a['numero']}", f"Convention de Bâle, annexe {a['numero']}",
                       f"{d['intitule']} — annexe {a['numero']} : {a.get('titre') or ''}", a["texte"], d.get("date"),
                       "en_vigueur", 1.0, statut_detail=detail, celex="BALE", num="annexe " + a["numero"])
    else:
        c.alertes["convention_bale.json absent"] += 1


# ---------------------------------------------------------------- arrêtés (copiés depuis Légifrance)
def charger_arretes(c):
    for chemin in sorted((DONNEES / "arretes").glob("*.json")):
        d = lire_json(chemin)
        nom = chemin.stem
        court = re.sub(r"^Arrêté du ", "Arrêté du ", d["intitule"])
        detail = (f"Arrêté ; copie de la version en vigueur affichée par Légifrance, données à jour au "
                  f"{d.get('mise_a_jour') or 'date inconnue'} : l'arrêté a pu être modifié depuis ; "
                  f"à vérifier sur Légifrance avant tout usage"
                  + (f" (NOR {d['nor']})" if d.get("nor") else ""))
        for a in d.get("articles", []):
            c.document("arrete_" + nom, "legislation", f"{nom}-art-{a['numero']}",
                       f"{court}, art. {a['numero']}", f"{d['intitule']} — article {a['numero']}", a["texte"],
                       d.get("date"), "en_vigueur", 1.1, statut_detail=detail, num=a["numero"])
        for a in d.get("annexes", []):
            c.document("arrete_" + nom, "legislation", f"{nom}-annexe-{a['numero'] or 'unique'}",
                       f"{court}, annexe {a['numero']}".strip(), f"{d['intitule']} — annexe {a['numero']}".strip(), a["texte"],
                       d.get("date"), "en_vigueur", 1.1, statut_detail=detail, num=("annexe " + a["numero"]).strip())


# ---------------------------------------------------------------- jurisprudence judiciaire (Judilibre)
def zones_judilibre(d):
    texte = d.get("text") or ""
    zones = d.get("zones") or {}
    segments = []
    for nom in ORDRE_ZONES:
        for sp in zones.get(nom) or []:
            try:
                seg = texte[sp["start"]:sp["end"]].strip()
            except (KeyError, TypeError):
                continue
            if seg:
                segments.append((ETIQUETTE_ZONE[nom], seg))
    if sum(len(s) for _, s in segments) < 0.3 * len(texte):
        return [("texte", texte)]
    return segments


def ref_judilibre(d):
    date = date_fr(d.get("decision_date"))
    if d.get("jurisdiction") == "cc":
        ch = CHAMBRES.get(d.get("chamber"), d.get("chamber") or "")
        pub = " (publié au Bulletin)" if "b" in (d.get("publication") or []) else ""
        return f"Cass. {ch}, {date}, n° {d.get('number')}{pub}"
    lieu = None
    tl = d.get("timeline") or []
    if tl and isinstance(tl[0], dict):
        lieu = (tl[0].get("jurisdiction") or "").replace("Cour d'appel d'", "").replace("Cour d'appel de ", "")
    lieu = lieu or str(d.get("location", "")).replace("ca_", "").replace("_", "-")
    return f"CA {lieu}, {date}, n° {d.get('number')}"


def charger_judilibre(c, fichier, source, poids, vus):
    chemin = DONNEES / fichier
    if not chemin.exists():
        c.alertes[f"{fichier} absent"] += 1
        return
    for d in lire_jsonl(chemin):
        if d["id"] in vus:
            continue
        vus.add(d["id"])
        ref = ref_judilibre(d)
        w = poids(d)
        date = d.get("decision_date")
        meta = {"juridiction": d.get("jurisdiction"), "chambre": d.get("chamber"), "numero": d.get("number"),
                "solution": d.get("solution") or d.get("solution_alt"), "publication": d.get("publication"),
                "pertinence_douane": d.get("pertinence_douane"), "niveau_general": d.get("niveau_general")}
        fiche = [ref]
        if d.get("themes"):
            fiche.append("Thèmes : " + ", ".join(map(str, d["themes"])))
        if d.get("summary"):
            fiche.append("Sommaire : " + d["summary"])
        visas = [v.get("title") for v in d.get("visa") or [] if isinstance(v, dict) and v.get("title")]
        if visas:
            fiche.append("Visa : " + " ; ".join(visas))
        if d.get("solution_alt") or d.get("solution"):
            fiche.append("Solution : " + str(d.get("solution_alt") or d.get("solution")))
        c.ajouter(source, "jurisprudence", d["id"], "fiche", ref, ref, "\n".join(fiche), date, "decision", w + 0.1,
                  section="fiche", **meta)
        k = 0
        for etiquette, seg in zones_judilibre(d):
            bonus = 0.1 if etiquette in ("motifs", "dispositif") else (-0.2 if etiquette == "moyens" else 0)
            for morceau in decouper(seg):
                k += 1
                c.ajouter(source, "jurisprudence", d["id"], k, ref, ref, morceau, date, "decision", w + bonus,
                          section=etiquette, **meta)


# ---------------------------------------------------------------- jurisprudence administrative et constitutionnelle
def chaines(o, chemin=()):
    if isinstance(o, str):
        yield chemin, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from chaines(v, chemin + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from chaines(v, chemin + (i,))


def en_clair(brut):
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", brut)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def charger_cetat(c):
    chemin = DONNEES / "juri_cetat_douane.jsonl"
    if not chemin.exists():
        c.alertes["juri_cetat_douane.jsonl absent"] += 1
        return
    base = {"forte": 1.1, "moyenne": 0.8, "faible": 0.6}
    for d in lire_jsonl(chemin):
        meta = d.get("meta") or {}
        date = en_date(meta.get("dateTexte")) or (d.get("annee") and f"{d['annee']}-01-01")
        w = base.get(d.get("pertinence_douane"), 0.6) + (0.2 if d.get("publication") in ("Lebon", "tables") else 0)
        ref = d.get("titre")
        c.document("jur_ce", "jurisprudence", d["id"], ref, ref, d.get("texte"), date, "decision", w,
                   juridiction=d.get("juridiction"), publication=d.get("publication"),
                   pertinence_douane=d.get("pertinence_douane"), numero=meta.get("num"))


def charger_constit(c):
    chemin = DONNEES / "juri_constit_filtree.jsonl"
    if not chemin.exists():
        c.alertes["juri_constit_filtree.jsonl absent"] += 1
        return
    for d in lire_jsonl(chemin):
        dec = d.get("decision") or {}
        cand = list(chaines(dec))
        texte = en_clair(max(cand, key=lambda x: len(x[1]))[1]) if cand else ""
        date = en_date(dec.get("dateTexte"))
        ref = d.get("titre")
        detail = f"Solution : {dec.get('solution')}" if dec.get("solution") else None
        c.document("jur_cc", "jurisprudence", d["id"], ref, ref, texte, date, "decision",
                   1.3 if d.get("niveau") == "A" else 1.0, statut_detail=detail, niveau=d.get("niveau"),
                   motifs=d.get("motifs"), numero=dec.get("num"), nature=dec.get("nature"))


# ---------------------------------------------------------------- CJUE
def charger_cjue(c):
    chemin = DONNEES / "cjue" / "cjue_douane_v2.jsonl"
    if not chemin.exists():
        c.alertes["cjue_douane_v2.jsonl absent"] += 1
        return
    for d in lire_jsonl(chemin):
        celex = d["celex"]
        m = re.match(r"6(\d{4})([A-Z]{2})(\d{4})", celex)
        affaire = ""
        if m:
            lettre = "T" if m.group(2).startswith("T") else "C"
            affaire = f" affaire {lettre}-{int(m.group(3))}/{m.group(1)[2:]}"
        typ = d.get("type") or "décision"
        date = d.get("date_decision")
        ref = f"CJUE, {typ}, {date_fr(date)},{affaire} (CELEX {celex})".replace(",,", ",")
        ag = "avocat" in typ.lower()
        detail = "Conclusions de l'avocat général : opinion non contraignante pour la Cour" if ag else None
        w = 0.8 if ag else 1.2
        c.document("cjue", "droit_ue_jurisprudence", celex, ref, ref, d.get("texte"), date, "decision", w,
                   statut_detail=detail, celex=celex, type=typ, pertinence=d.get("pertinence"),
                   textes_douaniers=d.get("textes_douaniers"))


# ---------------------------------------------------------------- doctrine (BOD)
def charger_doctrine(c):
    chemin = DONNEES / "bod" / "corpus_doctrine.jsonl"
    if not chemin.exists():
        c.alertes["corpus_doctrine.jsonl absent"] += 1
        return
    for d in lire_jsonl(chemin):
        abrogee = d.get("abrogee")
        statut = "abroge" if abrogee else "en_vigueur"
        par = d.get("abrogee_par")
        detail = (f"Décision administrative abrogée par : {', '.join(par)}" if par else
                  "Décision administrative abrogée" if abrogee else None)
        ref = f"DA {d['id']} du {date_fr(d.get('date_publication'))}"
        titre = f"{ref} — {d.get('titre') or ''} ({d.get('classement') or 'classement inconnu'})"
        meta = {"classement": d.get("classement"), "date_entree_en_vigueur": d.get("date_entree_en_vigueur"),
                "abrogee_par": par, "sans_contenu": d.get("sans_contenu"), "decoupage": d.get("decoupage")}
        if d.get("sans_contenu") or not (d.get("texte") or "").strip():
            note = "Texte non disponible dans le corpus (seule la fiche existe)."
            c.ajouter("doctrine", "doctrine", d["id"], "fiche", ref, titre, f"{titre}\n{note}\n{detail or ''}",
                      d.get("date_publication"), statut, 0.4, statut_detail=detail, section="fiche", **meta)
            continue
        c.document("doctrine", "doctrine", d["id"], ref, titre, d["texte"], d.get("date_publication"), statut,
                   0.5 if abrogee else 1.0, statut_detail=detail, **meta)


def charger_site(c):
    import hashlib
    from urllib.parse import unquote
    chemin = DONNEES / "site_douane.jsonl"
    if not chemin.exists():
        c.alertes["site_douane.jsonl absent (facultatif : python site_douane.py telecharger)"] += 1
        return
    vus = set()
    for d in lire_jsonl(chemin):
        url = d["url"]
        if "/bod/src/" in url or "/bod/" in url.lower() and url.lower().endswith(".pdf"):
            c.alertes["site : PDF de BOD ignorés (déjà dans la doctrine)"] += 1
            continue
        empreinte = hashlib.sha1(re.sub(r"\s+", " ", d["texte"]).strip().lower().encode()).hexdigest()
        if empreinte in vus:
            c.alertes["site : pages au contenu identique ignorées"] += 1
            continue
        vus.add(empreinte)
        pdf = d.get("type") == "pdf"
        titre = (d.get("titre") or url).strip()
        if titre.lower().startswith("actualités de la douane") or "/actualite" in url:
            c.alertes["site : pages d'actualités ignorées (listes de titres, bruit)"] += 1
            continue
        if pdf:
            titre = unquote(titre).rsplit("/", 1)[-1]
        ref = f"douane.gouv.fr — {'notice PDF : ' if pdf else ''}{titre}"
        maj = d.get("date_maj")
        detail = ("Information pratique du site douane.gouv.fr (valeur informative, pas un texte légal)"
                  + (f", mise à jour le {maj}" if maj else ", date de mise à jour inconnue") + " ; à confronter aux textes")
        c.document("site_douane", "information_officielle", url, ref, f"{ref} ({url})", d["texte"], maj,
                   "en_vigueur", 0.7 if pdf else 0.9, statut_detail=detail, url=url, type=d.get("type"))


# ---------------------------------------------------------------- orchestration
def main():
    with Collecteur() as c:
        charger_codes(c)
        charger_ue(c)
        charger_arretes(c)
        vus = set()
        forte = {"forte": 1.3, "moyenne": 1.0, "faible": 0.7}
        charger_judilibre(c, "jurisprudence_cassation_douane.jsonl", "jur_cass",
                          lambda d: forte.get(d.get("pertinence_douane"), 0.7) +
                          (0.2 if any(p in ("b", "r", "l", "c") for p in d.get("publication") or []) else 0), vus)
        charger_judilibre(c, "jurisprudence_generale_filtree.jsonl", "jur_cass_generale",
                          lambda d: 1.1 if d.get("niveau_general") == "A" else 0.8, vus)
        charger_judilibre(c, "jurisprudence_ca_douane.jsonl", "jur_ca",
                          lambda d: {"forte": 1.0, "moyenne": 0.8, "faible": 0.6}.get(d.get("pertinence_douane"), 0.6), vus)
        charger_cetat(c)
        charger_constit(c)
        charger_cjue(c)
        charger_doctrine(c)
        charger_site(c)

        lignes = ["Source | documents | passages | caractères | moyenne par passage"]
        tot_p = tot_c = 0
        for source, s in sorted(c.stats.items()):
            lignes.append(f"{source} | {len(s['docs'])} | {s['passages']} | {s['car']:,} | {s['car'] // max(1, s['passages'])}".replace(",", " "))
            tot_p += s["passages"]
            tot_c += s["car"]
        lignes.append(f"TOTAL | | {tot_p} | {tot_c:,} |".replace(",", " "))
        lignes.append("\n=== Alertes ===")
        lignes += [f"   {k} : {v}" for k, v in c.alertes.most_common()] or ["   aucune"]
        lignes.append("\n=== Exemples de passages (contrôle des références, dates et statuts) ===")
        for source, exs in sorted(c.exemples.items()):
            for p in exs:
                lignes.append(f"--- [{source}] {p['ref']}\n    date {p['date']} | statut {p['statut']} | poids {p['poids']} | "
                              f"section {p['section']} | {p['statut_detail'] or ''}\n    {re.sub(chr(10), ' ⏎ ', p['texte'][:200])!r}")
    texte = "\n".join(lignes)
    (SORTIE / "controle_passages.txt").write_text(texte, encoding="utf-8")
    print(texte)
    print("\nCopiez-collez ce résultat à Claude (ou envoyez-moi le fichier donnees\\index\\controle_passages.txt).")


if __name__ == "__main__":
    main()
