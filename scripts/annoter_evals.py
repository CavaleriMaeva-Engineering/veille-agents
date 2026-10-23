"""Annoter les cas d'évaluation du RAG : pour chaque question, dire quels extraits sont pertinents.

    uv run python scripts/annoter_evals.py              # annote les cas pas encore annotés (reprend où on s'est arrêté)
    uv run python scripts/annoter_evals.py --refaire r07

On montre l'union des 8 premiers résultats de BM25, du dense et du reranking (« pooling », comme dans les
campagnes d'évaluation TREC) : on ne juge que des candidats, pas tout le corpus. Chaque réponse est
enregistrée tout de suite : on peut quitter et reprendre.
"""

import argparse
import getpass
from datetime import date

from veille.evals.rag import (
    Annotation,
    charger_annotations,
    charger_cas,
    enregistrer_annotations,
    pool_candidats,
)
from veille.rag.documents import charger_corpus
from veille.rag.modeles import charger_encodeur, charger_reranker
from veille.rag.recherche import MoteurRecherche
from veille.storage.analyses import DOSSIER_SORTIES

parser = argparse.ArgumentParser()
parser.add_argument("--refaire", metavar="ID", help="réannoter un cas déjà annoté")
args = parser.parse_args()

cas = charger_cas()
annotations = charger_annotations()
a_faire = [c for c in cas if c.id == args.refaire] if args.refaire else [c for c in cas if c.id not in annotations]
if not a_faire:
    raise SystemExit("Tous les cas sont annotés. --refaire ID pour en reprendre un.")

morceaux, _ = charger_corpus([DOSSIER_SORTIES, DOSSIER_SORTIES / "archives"])
moteur = MoteurRecherche(morceaux, charger_encodeur(), charger_reranker())

for c in a_faire:
    candidats = pool_candidats(moteur, c)
    print(f"\n=== {c.id} ({c.type}) : {c.question}" + (f"  [marque : {c.marque}]" if c.marque else ""))
    if c.note:
        print(f"    note : {c.note}")
    for numero, m in enumerate(candidats, start=1):
        print(f"{numero:3}. [{m.marque} · {m.type} · {m.date}] {m.texte[:220]}")
    saisie = input("Numéros PERTINENTS séparés par des espaces (Entrée = aucun, q = quitter) : ").strip()
    if saisie.lower() == "q":
        break
    choisis = [candidats[int(n) - 1].id for n in saisie.split() if n.isdigit() and 1 <= int(n) <= len(candidats)]
    annotations[c.id] = Annotation(
        pertinents=choisis, candidats=[m.id for m in candidats],
        annote_par=getpass.getuser(), annote_le=date.today().isoformat(),
    )
    enregistrer_annotations(annotations)
    print(f"    → {len(choisis)} pertinent(s) enregistré(s)")

print(f"\n{len(annotations)} / {len(cas)} cas annotés.")
