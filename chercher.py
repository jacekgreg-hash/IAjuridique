#!/usr/bin/env python3
"""
Recherche dans le corpus (mots-clés, classement par pertinence × poids de la source). Aucun modèle d'IA : c'est le
premier maillon du futur assistant, qui doit d'abord retrouver les bons textes.

Utilisation :
   python chercher.py "visite domiciliaire nullité du procès-verbal"        # 10 meilleurs résultats
   python chercher.py "droit de se taire retenue douanière" -n 15
   python chercher.py "article 64 code des douanes" --faits 2025-03-01      # loi applicable à la date des faits
   python chercher.py "inscription de faux" --famille jurisprudence
   python chercher.py -a 64                                                 # article 64 (anciens/nouveaux codes, CPP)
   python chercher.py                                                       # mode interactif (une question par ligne)
Les résultats sont regroupés par famille : textes français, droit de l'Union, jurisprudence, CJUE, doctrine (--plat : un seul classement).
Par défaut, seul le nouveau code des douanes est affiché ; --ancien ajoute l'ancien code.
Options : -n NOMBRE   --source NOM (ex. jur_cass, jur_ce, code_cpp)   --famille legislation|jurisprudence|doctrine|droit_ue|information_officielle
          --faits AAAA-MM-JJ   --toutes-versions   --json   --base CHEMIN
Entre guillemets doubles dans la question : expression exacte, ex.  "droits de la défense"
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

BASE_DEFAUT = Path("donnees") / "index" / "corpus.db"
DATE_RECODIFICATION = "2026-05-01"
MOTS_VIDES = set("""a au aux avec ce ces dans de des du elle en et eux il je la le les leur lui ma mais me même mes moi mon ne
nos notre nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous c d j l m n s t y
été étée étées étés étant suis es est sommes êtes sont serai sera serait ont avait avoir être fait faire peut peuvent doit
dois doivent quel quelle quels quelles quand comment pourquoi est-ce cet cette ceux celle celles si ainsi alors donc or ni
car lors afin selon sans sous entre vers chez dont où""".split())


def racine(mot):
    """Troncature légère (pluriels, féminins) pour la recherche par préfixe : 'visites' -> 'visite', 'domiciliaires' -> 'domiciliair'."""
    if mot.endswith(("ès", "is", "us")) and len(mot) <= 7:
        return mot  # 'procès', 'accès', 'abus'... : le -s fait partie du mot
    for fin in ("ements", "ement", "ations", "ation", "eaux", "aux", "es", "s", "x", "e"):
        if mot.endswith(fin) and len(mot) - len(fin) >= 5:
            return mot[: -len(fin)]
    return mot


def requete_fts(question):
    expressions = re.findall(r'"([^"]+)"', question)
    reste = re.sub(r'"[^"]+"', " ", question)
    morceaux = []
    for e in expressions:
        mots = re.findall(r"\w+", e.lower())
        if mots:
            morceaux.append('"' + " ".join(mots) + '"')
    mots = [m for m in re.findall(r"\w+", reste.lower()) if m not in MOTS_VIDES and len(m) >= 2]
    def variantes(m):
        v = {m}
        if m.endswith("al"):
            v.add(m[:-2] + "aux")
        if m.endswith("aux"):
            v.add(m[:-3] + "al")
        if m.endswith("s"):
            v.add(m[:-1])
        elif not m.endswith("x"):
            v.add(m + "s")
        return sorted(v)
    for mot in mots:
        if any(c.isdigit() for c in mot):
            morceaux.append(f'"{mot}"')
        elif len(mot) >= 7 and racine(mot) != mot:
            morceaux.append(f'"{racine(mot)}"*')
        else:
            morceaux += [f'"{v}"' for v in variantes(mot)]
    # expressions contenant des mots vides au milieu ('valeur en douane', 'procès-verbal de saisie') : ils figurent dans le texte
    tous = re.findall(r"\w+", reste.lower())
    idx = [i for i, m in enumerate(tous) if m not in MOTS_VIDES and len(m) >= 2]
    for p, q in zip(idx, idx[1:]):
        if 1 <= q - p - 1 <= 2 and not any(t.isdigit() for t in (tous[p], tous[q])):
            fin = [tous[q]] + ([tous[q][:-1]] if tous[q].endswith("s") else [tous[q] + "s"] if len(tous[q]) < 7 else [])
            for f in fin:
                morceaux.append('"' + " ".join(tous[p:q] + [f]) + '"')
    # expressions de deux mots consécutifs : favorisent les passages où les termes se suivent ('procès-verbal', 'droit de se taire')
    for x, y in zip(mots, mots[1:]):
        if not (x.isdigit() or y.isdigit()):
            for vy in variantes(y) if len(y) < 7 else [y]:
                morceaux.append(f'"{x} {vy}"')
    return " OR ".join(morceaux)


def chercher(con, question, n=10, source=None, famille=None, faits=None, toutes_versions=False, par_document=2, ancien=False):
    fts = requete_fts(question)
    if not fts:
        return []
    cond, params = ["fts MATCH ?"], [fts]
    if source:
        cond.append("p.source = ?")
        params.append(source)
    if famille:
        cond.append("p.famille = ?")
        params.append(famille)
    if not toutes_versions and not ancien and (not faits or faits >= DATE_RECODIFICATION):
        # par défaut : nouveau code seulement ; l'ancien code sur demande (--ancien) ou si les faits sont antérieurs au 1er mai 2026
        cond.append("p.source != 'code_douanes_ancien'")
    sql = f"""
        SELECT p.id, p.pid, p.source, p.famille, p.doc_id, p.ref, p.section, p.date, p.statut, p.statut_detail, p.poids,
               -bm25(fts, 0.7, 1.0) AS pertinence, snippet(fts, 1, '«', '»', ' … ', 28) AS extrait, p.texte
        FROM fts JOIN passages p ON p.id = fts.rowid
        WHERE {' AND '.join(cond)}
        ORDER BY bm25(fts, 0.7, 1.0) LIMIT 400"""
    lignes = con.execute(sql, params).fetchall()
    cles = ["id", "pid", "source", "famille", "doc_id", "ref", "section", "date", "statut", "statut_detail", "poids",
            "pertinence", "extrait", "texte"]
    res = [dict(zip(cles, l)) for l in lignes]
    for r in res:
        coef = 0.7 if r["section"] == "moyens" else 1.0
        if faits and not toutes_versions:  # version non applicable aux faits : gardée, mais classée après
            if (r["source"] == "code_douanes_nouveau" and faits < DATE_RECODIFICATION) or \
               (r["source"] == "code_douanes_ancien" and faits >= DATE_RECODIFICATION):
                coef *= 0.8
        if r["source"] == "ue_32013R0952":
            coef *= 1.15  # hiérarchie : le règlement de base (code des douanes de l'Union) prime sur ses actes délégués et d'exécution
        r["score"] = round(r["pertinence"] * r["poids"] * coef, 2)
    res.sort(key=lambda r: -r["score"])
    retenus, par_doc = [], {}
    for r in res:
        cle = (r["source"], r["doc_id"])
        if par_doc.get(cle, 0) >= par_document:
            continue
        par_doc[cle] = par_doc.get(cle, 0) + 1
        retenus.append(r)
        if len(retenus) >= n:
            break
    return retenus


FAMILLES = [("legislation", "Textes législatifs et réglementaires français", 12),
            ("droit_ue", "Droit de l'Union (textes)", 3),
            ("jurisprudence", "Jurisprudence française", None),
            ("droit_ue_jurisprudence", "Jurisprudence de l'Union (CJUE)", 3),
            ("doctrine", "Doctrine administrative (BOD)", 3),
            ("information_officielle", "Informations pratiques (site douane.gouv.fr)", 4)]


GENERIQUES = set("""article articles relatif relatifs relative relatives concernant concerne regles règles texte textes code douane douanes
douanier douaniere douanière douaniers procedure procédure dispositions disposition cas quelle quelles quel quels""".split())
_CHEMINS = {}


def _norm(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def sections(con, question, faits=None, ancien=False, toutes_versions=False, max_sections=3, max_articles=40):
    """Sections (chapitres) des codes dont l'INTITULÉ correspond à la question : renvoie tous leurs articles, même ceux dont
    le texte n'emploie pas les mots de la question (ex. 'visite domiciliaire' -> tous les articles de la section)."""
    mots = [_norm(m) for m in re.findall(r"\w+", question.lower()) if m not in MOTS_VIDES and len(m) >= 4 and m not in GENERIQUES
            and _norm(m) not in {_norm(g) for g in GENERIQUES}]
    if not mots:
        return []
    racines = [racine(m) if len(m) >= 6 else m for m in mots]
    cle = id(con)
    if cle not in _CHEMINS:
        _CHEMINS[cle] = con.execute("""SELECT DISTINCT source, json_extract(meta, '$.chemin') FROM passages
                                       WHERE source IN ('code_douanes_ancien','code_douanes_nouveau','code_cpp')
                                       AND json_extract(meta, '$.chemin') IS NOT NULL""").fetchall()
    visibles = set(["code_douanes_nouveau", "code_cpp"])
    if toutes_versions or ancien or (faits and faits < DATE_RECODIFICATION):
        visibles.add("code_douanes_ancien")
    # pour chaque chemin, le segment (livre, titre, chapitre, section…) dont l'intitulé contient tous les mots, le plus court
    # d'abord (le plus précis) ; on regroupe ensuite TOUS les articles situés sous ce segment, sous-sections comprises.
    portees = {}
    for source, chemin in _CHEMINS[cle]:
        if source not in visibles:
            continue
        segments = [s.strip() for s in chemin.split(">")]
        meilleur = None
        for i, seg in enumerate(segments):
            sn = _norm(seg)
            if all(r in sn for r in racines) and (meilleur is None or len(sn) < meilleur[0]):
                meilleur = (len(sn), i)
        if meilleur:
            portee = " > ".join(segments[: meilleur[1] + 1])
            portees[(source, portee)] = meilleur[0]
    out = []
    for (source, portee), _ in sorted(portees.items(), key=lambda kv: (kv[1], kv[0][1]))[:max_sections]:
        motif = portee.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + " > %"
        lignes = con.execute("""SELECT p.ref, p.doc_id, p.pid, p.texte, p.date, p.statut, p.statut_detail, p.famille, p.source, p.id
                                FROM passages p WHERE p.source = ?
                                AND (json_extract(p.meta, '$.chemin') = ? OR json_extract(p.meta, '$.chemin') LIKE ? ESCAPE '\\')
                                ORDER BY p.id""", (source, portee, motif)).fetchall()
        vus, arts = set(), []
        for ref, doc_id, pid, texte, date, statut, detail, famille, src, pid_int in lignes:
            if doc_id in vus:
                continue
            vus.add(doc_id)
            arts.append({"ref": ref, "pid": pid, "texte": texte, "date": date, "statut": statut, "statut_detail": detail,
                         "famille": famille, "source": src, "doc_id": doc_id, "section": "texte", "extrait": texte[:200], "score": 0})
        if arts:
            out.append({"intitule": portee, "source": source, "articles": arts[:max_articles], "total": len(arts)})
    return out


PLAFONDS = {"legislation": {"code_cpp": 2}}  # le CPP (4 600 articles) ne doit pas écraser les textes douaniers


def chercher_groupes(con, question, n_juris, n_par_famille=None, n_textes=None, **filtres):
    """Un classement séparé par famille de sources : le meilleur de chaque famille, plutôt qu'un seul classement où la
    jurisprudence, plus abondante, écraserait les textes."""
    groupes = []
    for famille, titre, quota in FAMILLES:
        n = n_par_famille or (n_textes if famille == "legislation" and n_textes else None) or quota or n_juris
        res = chercher(con, question, n * 3, famille=famille, par_document=1, **filtres)
        plafonds, compte, retenus = PLAFONDS.get(famille, {}), {}, []
        for r in res:
            if r["source"] in plafonds and compte.get(r["source"], 0) >= plafonds[r["source"]]:
                continue
            compte[r["source"]] = compte.get(r["source"], 0) + 1
            retenus.append(r)
            if len(retenus) >= n:
                break
        res = retenus
        if res:
            groupes.append((titre, res))
    return groupes


RE_CONCORD = re.compile(r"\s*Correspondance (?:ancien/nouveau code|[^:{]{0,60}?)\s*(?:\([^)]*\))?\s*:\s*(\{.*\})\s*$", re.S)


def separer_concordance(texte):
    """Sépare le texte de l'article du tableau de concordance (JSON) ajouté à la fin. Renvoie (texte, note lisible)."""
    m = RE_CONCORD.search(texte or "")
    if not m:
        return texte, ""
    try:
        d = json.loads(m.group(1))
    except ValueError:
        try:
            import ast
            d = ast.literal_eval(m.group(1))  # dictionnaire écrit avec des apostrophes
        except (ValueError, SyntaxError):
            return texte, ""
    if not isinstance(d, dict):
        return texte, ""
    eq = []
    for e in d.get("equivalents") or []:
        eq += [str(v) for k, v in e.items() if k in ("nouveau", "ancien") and v]
    statut = d.get("statut")
    if eq:
        note = "Correspondance (table officielle 2026) : " + ", ".join(eq) + (f" [{statut}]" if statut else "")
    elif statut:
        note = f"Correspondance (table officielle 2026) : {statut}, pas d'équivalent indiqué"
    else:
        note = ""
    return texte[: m.start()].rstrip(), note


def par_article(con, numero, n=20):
    num = re.sub(r"[\s.]", "", numero)  # 'L. 443-1', 'L443-1' ou 'l 443-1' : même article
    sql = """SELECT p.pid, p.source, p.ref, p.date, p.statut, p.statut_detail, substr(p.texte, 1, 400), json_extract(p.meta, '$.chemin')
             FROM passages p WHERE (p.source IN ('code_douanes_ancien','code_douanes_nouveau','code_cpp') OR p.source LIKE 'ue\\_%' ESCAPE '\\')
             AND upper(replace(replace(replace(json_extract(p.meta, '$.num'), ' ', ''), '.', ''), char(160), '')) = upper(?) ORDER BY p.source, p.id LIMIT ?"""
    return con.execute(sql, (num, n)).fetchall()


def expliquer(con, question, article, faits=None):
    lignes = par_article(con, article, 50)
    if not lignes:
        print(f"Article {article} : aucun passage trouvé dans la base (numéro non reconnu, ou texte absent du corpus).")
        return
    fts = requete_fts(question)
    print(f"Requête interne : {fts}\n")
    rangs = {}
    for fam in ("legislation", "droit_ue"):
        tous = chercher(con, question, 100000, famille=fam, par_document=99, faits=faits)
        rangs[fam] = ({r["pid"]: (i, r) for i, r in enumerate(tous, 1)}, tous)
    for pid, source, ref, date, statut, detail, debut, _chemin in lignes:
        fam = "droit_ue" if source.startswith("ue_") else "legislation"
        rang, tous = rangs[fam]
        print(f"{ref} [{statut}] {date or ''} (source {source})")
        print("   début : " + re.sub(r"\s+", " ", debut)[:200])
        if pid in rang:
            i, r = rang[pid]
            print(f"   → trouvé : rang {i} parmi {len(tous)} textes de cette famille, score {r['score']} (comparer au score des premiers ci-dessous)")
        else:
            print("   → ne contient aucun des mots de la requête, ou masqué (ancien code sans --faits) : non trouvé")
        print()
    for fam, (_, tous) in rangs.items():
        if tous:
            print(f"Scores des 8 premiers ({fam}) : " + ", ".join(str(r["score"]) for r in tous[:8]))


def afficher(res, faits=None):
    if not res:
        print("Aucun résultat.")
    for i, r in enumerate(res, 1):
        alerte = ""
        if r["statut"] == "abroge" and r["source"] == "code_douanes_ancien" and faits and faits < DATE_RECODIFICATION:
            alerte = "   ℹ Ancien code, applicable à la date des faits indiquée (avant le 1er mai 2026)"
        elif r["source"] == "code_douanes_nouveau" and faits and faits < DATE_RECODIFICATION:
            alerte = ("   ⚠ Nouveau code (en vigueur depuis le 1er mai 2026) : pas applicable aux faits antérieurs. "
                      "Une règle de procédure peut toutefois s'appliquer aux procédures en cours : à vérifier.")
        elif r["statut"] == "abroge":
            alerte = "   ⚠ " + (r["statut_detail"] or "texte abrogé")
        elif r["statut_detail"] and r["famille"] in ("legislation", "droit_ue", "doctrine", "droit_ue_jurisprudence", "information_officielle"):
            alerte = "   ℹ " + r["statut_detail"]
        print(f"{i:>2}. [{r['score']}] {r['ref']}")
        print(f"    {r['famille']} · {r['date'] or 'date inconnue'} · {r['section'] or 'texte'} · source {r['source']}")
        if alerte:
            print(alerte)
        extrait = re.sub(r"\s+", " ", r["extrait"])
        _, note = separer_concordance(r.get("texte"))
        if "Correspondance" in extrait:  # extrait coupé sur le JSON de concordance : on le retire
            extrait = extrait[: extrait.index("Correspondance")].rstrip() + " …"
        print("    " + extrait)
        if note:
            print("    ↔ " + note)
        print()


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("question", nargs="?")
    ap.add_argument("-n", type=int, default=8, help="nombre de décisions de jurisprudence françaises (défaut 8)")
    ap.add_argument("--textes", type=int, default=12, help="nombre de textes législatifs affichés (défaut 12)")
    ap.add_argument("--plat", action="store_true", help="un seul classement, sans regroupement par famille")
    ap.add_argument("--source")
    ap.add_argument("--famille")
    ap.add_argument("--faits")
    ap.add_argument("--toutes-versions", action="store_true")
    ap.add_argument("--ancien", action="store_true", help="affiche aussi l'ancien code des douanes (masqué par défaut sans date de faits)")
    ap.add_argument("-a", "--article")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--expliquer", metavar="ARTICLE", help="avec une question : explique où se classe cet article et pourquoi")
    ap.add_argument("--base", default=str(BASE_DEFAUT))
    a = ap.parse_args()
    if not Path(a.base).exists():
        sys.exit(f"Base introuvable : {a.base} (lancez d'abord index_passages.py)")
    con = sqlite3.connect(a.base)

    if a.article:
        for pid, source, ref, date, statut, detail, debut, chemin in par_article(con, a.article):
            print(f"{ref} [{statut}] {date or ''}\n   Section : {chemin or 'inconnue'}\n   {(detail or '')}\n   {re.sub(chr(10), ' ', debut)}\n")
        return
    if a.expliquer:
        expliquer(con, a.question or "", a.expliquer, a.faits)
        return
    questions = [a.question] if a.question else None
    while True:
        q = questions.pop() if questions else (input("Question > ").strip() if not a.question else None)
        if not q:
            break
        if a.plat or a.famille or a.source:
            groupes = [("Résultats", chercher(con, q, a.n, a.source, a.famille, a.faits, a.toutes_versions, ancien=a.ancien))]
        else:
            groupes = chercher_groupes(con, q, a.n, n_textes=a.textes, source=None, faits=a.faits, toutes_versions=a.toutes_versions, ancien=a.ancien)
        if a.json:
            print(json.dumps([{"famille": t, "resultats": r} for t, r in groupes], ensure_ascii=False, indent=1))
        else:
            if not any(r for _, r in groupes):
                print("Aucun résultat.")
            if not a.faits and not a.ancien and not a.toutes_versions:
                print("(Nouveau code des douanes affiché. Ancien code : ajoutez --ancien, ou --faits AAAA-MM-JJ pour une date antérieure au 1er mai 2026.)\n")
            if not (a.plat or a.famille or a.source):
                for s in sections(con, q, a.faits, a.ancien, a.toutes_versions):
                    print(f"━━━ Section dont l'intitulé correspond : {s['intitule'].split('>')[-1].strip()} ━━━")
                    print(f"    {s['intitule']}")
                    print(f"    {s['total']} article(s) :")
                    for art in s["articles"]:
                        print(f"      - {art['ref']} : " + re.sub(r"\s+", " ", separer_concordance(art["texte"])[0])[:90])
                    print()
            for titre, res in groupes:
                print(f"━━━ {titre} ━━━\n")
                afficher(res, a.faits)

        if a.question:
            break


if __name__ == "__main__":
    main()
