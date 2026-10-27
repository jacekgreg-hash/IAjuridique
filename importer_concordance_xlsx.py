#!/usr/bin/env python3
"""
Importe la table de concordance officielle (xlsx de Légifrance) et la recoupe
avec les fichiers déjà téléchargés. Aucun appel réseau.

Prérequis (une seule fois) :  pip install openpyxl

Utilisation :
  python importer_concordance_xlsx.py                      # cherche un .xlsx « concordance » ici ou dans donnees\\
  python importer_concordance_xlsx.py CHEMIN_DU_FICHIER.xlsx [DOSSIER_DONNEES]

Produit  donnees\\concordance_officielle.json  et affiche un bilan de contrôle.
"""

import json
import re
import sys
from pathlib import Path

try:
    import openpyxl
except ModuleNotFoundError:
    sys.exit("Module manquant : lancez d'abord  pip install openpyxl")

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
dossier = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("donnees")

if len(sys.argv) > 1:
    chemin_xlsx = Path(sys.argv[1])
else:
    candidats = list(Path(".").glob("*oncordance*.xlsx")) + list(dossier.glob("*oncordance*.xlsx"))
    if not candidats:
        sys.exit("Fichier xlsx introuvable. Indiquez son chemin en argument.")
    chemin_xlsx = candidats[0]
if not chemin_xlsx.exists():
    sys.exit(f"Fichier introuvable : {chemin_xlsx}")

TEXTE_CODE = "Code des douanes"
TEXTE_NOUVEAU = "Nouvel article"


# ---------------------------------------------------------------------------
# Normalisation des références
# ---------------------------------------------------------------------------
def norm_ancien(ref):
    """'art. 1er' -> '1' ; 'art. 2 bis' -> '2 bis'."""
    r = str(ref or "").strip()
    r = re.sub(r"^art(?:icles?)?\.?\s*", "", r, flags=re.I)
    r = re.sub(r"^(\d+)\s*er\b", r"\1", r)
    return re.sub(r"\s+", " ", r).strip()


def norm_nouveau(ref):
    """'L. 121-2' -> 'L121-2' ; 'abrogé' -> None."""
    r = str(ref or "").strip()
    if not r or r.lower().startswith("abrog"):
        return None
    r = re.sub(r"^([LRDA])\.\s*", r"\1", r)
    return re.sub(r"\s+", "", r)


# ---------------------------------------------------------------------------
# Lecture du tableau
# ---------------------------------------------------------------------------
wb = openpyxl.load_workbook(chemin_xlsx, data_only=True)
ws = wb.worksheets[0]

lignes = []
for ligne in ws.iter_rows(min_row=3, values_only=True):
    texte, ancienne, precision, nouvelle = (list(ligne) + [None] * 4)[:4]
    if not texte:
        continue
    lignes.append((str(texte).strip(), ancienne, precision, nouvelle))

ancien_vers_nouveau = {}   # code des douanes : n° ancien -> liste d'équivalents
autres_textes = []         # décrets, arrêtés, autres codes recodifiés
nouveaux_articles = []     # articles créés, sans équivalent ancien
nouveau_vers_ancien = {}   # n° nouveau -> origines

for texte, ancienne, precision, nouvelle in lignes:
    nouveau = norm_nouveau(nouvelle)
    precision = (str(precision).strip() if precision not in (None, "") else None)

    if texte == TEXTE_NOUVEAU:
        if nouveau:
            nouveaux_articles.append(nouveau)
        continue

    entree = {
        "nouveau": nouveau,
        "statut": "repris" if nouveau else "abrogé",
        "precision": precision,
    }
    if texte == TEXTE_CODE:
        ancien_vers_nouveau.setdefault(norm_ancien(ancienne), []).append(entree)
    else:
        autres_textes.append({"texte": texte, "ancienne_ref": norm_ancien(ancienne), **entree})

    if nouveau:
        nouveau_vers_ancien.setdefault(nouveau, []).append({
            "texte": texte,
            "ancienne_ref": norm_ancien(ancienne),
            "precision": precision,
        })

sortie = {
    "source": chemin_xlsx.name,
    "ancien_vers_nouveau": ancien_vers_nouveau,
    "nouveaux_articles": sorted(set(nouveaux_articles)),
    "autres_textes": autres_textes,
    "nouveau_vers_ancien": nouveau_vers_ancien,
}
dossier.mkdir(exist_ok=True)
(dossier / "concordance_officielle.json").write_text(
    json.dumps(sortie, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# Bilan
# ---------------------------------------------------------------------------
print(f"Fichier : {chemin_xlsx.name}")
print(f"Lignes de données : {len(lignes)}")
print(f"\nCode des douanes (ancien) : {len(ancien_vers_nouveau)} articles distincts")
tout_abroge = [n for n, v in ancien_vers_nouveau.items() if all(e["statut"] == "abrogé" for e in v)]
partiel = [n for n, v in ancien_vers_nouveau.items()
           if any(e["statut"] == "abrogé" for e in v) and any(e["statut"] == "repris" for e in v)]
scindes = [n for n, v in ancien_vers_nouveau.items() if len({e["nouveau"] for e in v if e["nouveau"]}) > 1]
print(f"  entièrement abrogés : {len(tout_abroge)}")
print(f"  repris (au moins en partie) : {len(ancien_vers_nouveau) - len(tout_abroge)}")
print(f"     dont abrogés en partie seulement : {len(partiel)}")
print(f"     dont scindés en plusieurs nouveaux articles : {len(scindes)}")
print(f"Nouveaux articles sans équivalent ancien : {len(set(nouveaux_articles))}")
print(f"Lignes d'autres textes (décrets, arrêtés, autres codes) : {len(autres_textes)}")

print("\nArticles souvent cités par la jurisprudence :")
for num in ("60", "63 ter", "64", "354", "369", "370", "414", "414-2", "415", "417", "419", "426", "391"):
    v = ancien_vers_nouveau.get(num)
    if not v:
        print(f"  ancien {num:7s} : absent du tableau")
        continue
    morceaux = []
    for e in v:
        cible = e["nouveau"] or "abrogé"
        morceaux.append(cible + (f" [{e['precision']}]" if e["precision"] else ""))
    print(f"  ancien {num:7s} -> {' ; '.join(morceaux)}")

# ---------------------------------------------------------------------------
# Recoupement avec les fichiers téléchargés (si présents)
# ---------------------------------------------------------------------------
print("\n=== RECOUPEMENT ===")


def charger(nom):
    chemin = dossier / nom
    return json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else None


def api_depuis_brut(brut):
    """Lit concordance_brute.json (réponses de l'API) : n° ancien -> liste de nouveaux n°."""
    resultat = {}
    for item in brut:
        liens = []
        for texte in (item.get("reponse") or {}).get("newTexts") or []:
            m = re.search(r"art\.\s*(.+?)\s*(?:\(([A-Z_]+)\))?\s*$", texte.get("name") or "")
            if m:
                liens.append({"num": m.group(1).strip().replace(" ", "")})
        if liens:
            resultat[str(item.get("num")).strip()] = liens
    return resultat


ancien_fichier = charger("code_douanes_ancien_articles.json")
nouveau_fichier = charger("code_douanes_nouveau_articles.json")
api = charger("concordance_ancien_vers_nouveau.json")
if api is None:
    brut = charger("concordance_brute.json")
    if brut:
        api = api_depuis_brut(brut)
        print("(concordance de l'API relue depuis concordance_brute.json)")
nums_anciens = set()

if ancien_fichier:
    nums_anciens = {str(a.get("num")).strip() for a in ancien_fichier}
    manquants = sorted(nums_anciens - set(ancien_vers_nouveau))
    print(f"Anciens articles téléchargés ({len(nums_anciens)}) absents du tableau : {len(manquants)}")
    for n in manquants:
        liens = (api or {}).get(n)
        if liens:
            cible = ", ".join(l["num"] for l in liens)
        else:
            cible = "aucun lien dans l'API" if api else "(API non disponible)"
        print(f"   ancien {n:22s} -> API : {cible}")
else:
    print("(fichier de l'ancien code non trouvé : recoupement ignoré)")

if nouveau_fichier:
    nums_nouveaux = {str(a.get("num")).strip() for a in nouveau_fichier}
    dans_tableau = set(nouveau_vers_ancien) | set(nouveaux_articles)
    absents_fichier = sorted(dans_tableau - nums_nouveaux)
    absents_tableau = sorted(nums_nouveaux - dans_tableau)
    print(f"Nouveaux articles cités par le tableau : {len(dans_tableau)} ; téléchargés : {len(nums_nouveaux)}")
    print(f"  cités par le tableau mais absents du téléchargement : {len(absents_fichier)} {absents_fichier[:12]}")
    print(f"  téléchargés mais absents du tableau : {len(absents_tableau)} {absents_tableau[:12]}")
else:
    print("(fichier du nouveau code non trouvé : recoupement ignoré)")

if api:
    base = nums_anciens if nums_anciens else set(api)
    identiques = differents = 0
    api_vide, tableau_abroge, exemples = [], [], []
    for num in sorted(base):
        v = ancien_vers_nouveau.get(num)
        if not v:
            continue
        cible_xlsx = {e["nouveau"] for e in v if e["nouveau"]}
        cible_api = {l["num"].replace(" ", "") for l in api.get(num, [])}
        if cible_api == cible_xlsx:
            identiques += 1
        elif not cible_api:
            api_vide.append(num)
        elif not cible_xlsx:
            tableau_abroge.append(num)
        else:
            differents += 1
            if len(exemples) < 10:
                exemples.append((num, sorted(cible_api), sorted(cible_xlsx)))
    print(f"Comparaison avec l'API (articles présents dans le tableau) :")
    print(f"   identiques : {identiques}")
    print(f"   le tableau indique un équivalent, l'API aucun : {len(api_vide)} {api_vide[:10]}")
    print(f"   le tableau indique « abrogé », l'API un équivalent : {len(tableau_abroge)} {tableau_abroge[:10]}")
    print(f"   équivalents différents : {differents}")
    for num, a, x in exemples:
        print(f"      ancien {num} : API {a} | tableau {x}")
else:
    print("(concordance de l'API non trouvée : comparaison ignorée)")

# ---------------------------------------------------------------------------
# Fusion tableau officiel + API -> concordance_finale.json
# ---------------------------------------------------------------------------
print("\n=== FUSION ===")


def cle_naturelle(n):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", n)]


anciens_connus = set(ancien_vers_nouveau) | set(api or {}) | set(nums_anciens)
finale = {}
divergences = []
sans_equivalent = []
ajouts_api = 0

for num in sorted(anciens_connus, key=cle_naturelle):
    equivalents = {}
    lignes_tableau = ancien_vers_nouveau.get(num, [])
    for e in lignes_tableau:
        if e["nouveau"]:
            d = equivalents.setdefault(e["nouveau"], {"nouveau": e["nouveau"], "sources": [], "precisions": []})
            if "tableau" not in d["sources"]:
                d["sources"].append("tableau")
            if e["precision"]:
                d["precisions"].append(e["precision"])
    liens_api = (api or {}).get(num, [])
    for lien in liens_api:
        n = lien["num"].replace(" ", "")
        if not re.match(r"^[LRDA]\d", n):      # l'API cite parfois un ancien numéro : ignoré
            continue
        d = equivalents.setdefault(n, {"nouveau": n, "sources": [], "precisions": []})
        if "api" not in d["sources"]:
            d["sources"].append("api")

    parties_abrogees = [e["precision"] or "tout l'article" for e in lignes_tableau if e["statut"] == "abrogé"]
    if equivalents:
        statut = "repris"
    elif parties_abrogees:
        statut = "abrogé"
    else:
        statut = "sans équivalent connu"
        sans_equivalent.append(num)

    cible_tableau = {e["nouveau"] for e in lignes_tableau if e["nouveau"]}
    cible_api = {l["num"].replace(" ", "") for l in liens_api if re.match(r"^[LRDA]\d", l["num"].replace(" ", ""))}
    divergence = bool(cible_tableau and cible_api and cible_tableau != cible_api)
    if divergence:
        divergences.append(num)
    ajouts_api += sum(1 for d in equivalents.values() if d["sources"] == ["api"])

    finale[num] = {
        "statut": statut,
        "equivalents": sorted(equivalents.values(), key=lambda d: cle_naturelle(d["nouveau"])),
        "parties_abrogees": parties_abrogees,
        "divergence_entre_sources": divergence,
    }

inverse = {}
for num, f in finale.items():
    for d in f["equivalents"]:
        inverse.setdefault(d["nouveau"], []).append({"ancien": num, "precisions": d["precisions"]})

(dossier / "concordance_finale.json").write_text(json.dumps({
    "sources": [chemin_xlsx.name, "API Légifrance (concordanceLinksArticle)"],
    "ancien_vers_nouveau": finale,
    "nouveau_vers_ancien": {k: inverse[k] for k in sorted(inverse, key=cle_naturelle)},
    "nouveaux_articles_sans_ancien": sorted(set(nouveaux_articles), key=cle_naturelle),
    "autres_textes": autres_textes,
}, ensure_ascii=False, indent=2), encoding="utf-8")

par_statut = {}
for f in finale.values():
    par_statut[f["statut"]] = par_statut.get(f["statut"], 0) + 1
print(f"Anciens articles dans la concordance finale : {len(finale)}")
print(f"   par statut : {par_statut}")
print(f"   articles où le tableau et l'API divergent : {len(divergences)}")
print(f"   équivalents apportés par l'API seule : {ajouts_api}")
print(f"   sans équivalent connu (à vérifier, {len(sans_equivalent)}) : {', '.join(sans_equivalent)}")
print("\nÉcrit : concordance_officielle.json et concordance_finale.json.")
print("Copiez-collez à Claude uniquement la partie qui suit « FUSION ».")
