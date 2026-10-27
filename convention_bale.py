"""Convention de Bâle (texte français, PDF converti en texte) -> donnees\\bale\\convention_bale.json

Usage :  python convention_bale.py "chemin\\vers\\BaselConventionText-f.pdf.txt"
Découpe : préambule, articles 1 à 29, annexes I à IX (le Protocole sur la responsabilité n'est pas repris).
"""
import json, re, sys
from pathlib import Path

SORTIE = Path("donnees") / "bale" / "convention_bale.json"
INTITULE = "Convention de Bâle sur le contrôle des mouvements transfrontières de déchets dangereux et de leur élimination"


def nettoyer(lignes):
    out = []
    for l in lignes:
        s = l.rstrip()
        if re.fullmatch(r"\|\s*\d+", s.strip()) or s.strip() in ("A", ""):
            continue
        out.append(s)
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 1
    brut = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
    # début du texte de la Convention : première ligne « PREAMBULE » ; fin : début du Protocole (2e occurrence du titre
    # « PROTOCOLE SUR LA RESPONSABILITÉ ET » suivie de « L'INDEMNISATION » après l'annexe IX)
    deb = next(i for i, l in enumerate(brut) if l.strip().startswith("PREAMBULE"))
    ann_ix = next(i for i, l in enumerate(brut) if re.match(r"ANNEXE IX\d*\s*$", l.strip()))
    fin = next(i for i in range(ann_ix, len(brut)) if brut[i].strip().startswith("PROTOCOLE SUR LA RESPONSABILIT"))
    lignes = nettoyer(brut[deb:fin])

    articles, annexes, preambule = [], [], []
    courant, mode = None, "preambule"
    for l in lignes:
        t = l.strip()
        m = re.fullmatch(r"ARTICLE\s+(PREMIER|\d{1,2})", t)
        if mode != "annexes" and m:
            num = 1 if m.group(1) == "PREMIER" else int(m.group(1))
            if num > 29:          # note de bas de page collée au numéro (« ARTICLE 43 » = article 4 + note 3)
                num = int(str(num)[:-1])
            courant = {"numero": str(num), "titre": "", "lignes": []}
            articles.append(courant); mode = "article"; continue
        if t == "ANNEXES":
            mode = "annexes"; courant = None; continue
        m = re.fullmatch(r"ANNEXE\s+([IVX]+(?:\s+[AB])?)\d*", t)
        if mode == "annexes" and m:
            courant = {"numero": m.group(1).replace("  ", " "), "titre": "", "lignes": []}
            annexes.append(courant); continue
        if mode == "preambule":
            preambule.append(l)
        elif courant is not None:
            if not courant["titre"] and t.isupper() and len(t) < 90:
                courant["titre"] = t.title(); continue
            courant["lignes"].append(l)
    for a in articles + annexes:
        a["texte"] = re.sub(r"\s*\n\s*", " ", "\n".join(a.pop("lignes"))).strip()
        a["texte"] = re.sub(r"(\d+\.|[a-z]\)) ", lambda m: "\n" + m.group(0), a["texte"]).strip() if len(a["texte"]) < 12000 else a["texte"]
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({"intitule": INTITULE, "date": "1989-03-22", "preambule": " ".join(nettoyer(preambule)),
                                  "articles": articles, "annexes": annexes}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ok : {len(articles)} articles (de {articles[0]['numero']} à {articles[-1]['numero']}), {len(annexes)} annexes "
          f"({', '.join(a['numero'] for a in annexes)}), {sum(len(a['texte']) for a in articles + annexes)} caractères")
    for a in articles[:4]:
        print("  art.", a["numero"], "|", a["titre"], "|", a["texte"][:70].replace("\n", " "))
    print("\nCopiez-collez ce résultat à Claude.")


if __name__ == "__main__":
    sys.exit(main())
