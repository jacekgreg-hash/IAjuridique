"""Arrêté copié depuis Légifrance (fichier texte) -> donnees\\arretes\\<nom>.json

Usage :  python arrete_texte.py "fichier.txt" stupefiants_1990
Le fichier est la copie de la page Légifrance (version en vigueur). Le script lit le titre, la date de mise à jour
des données indiquée par Légifrance, le NOR, les articles et les annexes.
"""
import json, re, sys
from pathlib import Path

SORTIE = Path("donnees") / "arretes"


def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    brut = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
    lignes = [l.strip() for l in brut]
    titre = next(l for l in lignes if l)
    mise_a_jour = next((re.search(r":\s*(.+)$", l).group(1).strip() for l in lignes
                        if l.startswith("Dernière mise à jour")), None)
    nor = next((l.split(":", 1)[1].strip() for l in lignes if l.startswith("NOR")), None)
    m = re.search(r"du (\d{1,2}(?:er)?) (\w+) (\d{4})", titre)
    mois = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
            "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}
    date = f"{int(m.group(3)):04d}-{mois[m.group(2)]:02d}-{int(m.group(1).replace('er', '')):02d}" if m else None

    articles, annexes, courant, signature = [], [], None, False
    for l in lignes:
        if l.startswith("Fait à "):
            signature = True
        if signature:
            continue
        ma = re.fullmatch(r"Article\s+(\d+(?:-\d+)*)", l)
        mx = re.fullmatch(r"Annexe\s+([IVX]+)", l)
        if ma:
            courant = {"numero": ma.group(1), "lignes": []}; articles.append(courant); continue
        if mx:
            courant = {"numero": mx.group(1), "lignes": []}; annexes.append(courant); continue
        if l.startswith("Annexes (Articles"):
            courant = None; continue
        if courant is not None and l:
            courant["lignes"].append(l)
    for a in articles + annexes:
        a["texte"] = "\n".join(a.pop("lignes"))
    SORTIE.mkdir(parents=True, exist_ok=True)
    (SORTIE / f"{sys.argv[2]}.json").write_text(json.dumps(
        {"intitule": titre, "date": date, "nor": nor, "mise_a_jour": mise_a_jour,
         "articles": articles, "annexes": annexes}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ok : {titre}")
    print(f"   date {date} | NOR {nor} | données à jour au {mise_a_jour}")
    print(f"   {len(articles)} articles ({', '.join(a['numero'] for a in articles)}), "
          f"{len(annexes)} annexes ({', '.join(a['numero'] for a in annexes)}), "
          f"{sum(len(a['texte']) for a in articles + annexes)} caractères")
    print("\nCopiez-collez ce résultat à Claude.")


if __name__ == "__main__":
    sys.exit(main())
