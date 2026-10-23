"""Interroger l'historique de veille.

    uv run python scripts/rag.py "Quelles offres de coffret ont été vues ?"
    uv run python scripts/rag.py "pubs vidéo les plus durables" --marque Typology --comparer
"""

import argparse
import logging
import uuid
from pathlib import Path

from veille.llm.client import creer_client_groq
from veille.rag.documents import charger_corpus
from veille.rag.modeles import charger_encodeur, charger_reranker
from veille.rag.recherche import MODES, MoteurRecherche
from veille.rag.reponse import repondre
from veille.settings import Secrets, charger_config

logging.basicConfig(level=logging.WARNING, format="%(message)s")

parser = argparse.ArgumentParser(description="Recherche hybride + reranking sur l'historique de veille")
parser.add_argument("question")
parser.add_argument("--marque", help="ne chercher que dans cette marque")
parser.add_argument("-k", type=int, default=5, help="nombre d'extraits retenus")
parser.add_argument("--comparer", action="store_true", help="afficher BM25, dense, hybride et reranking côte à côte")
parser.add_argument("--sans-reponse", action="store_true", help="recherche seule, sans appel au LLM")
args = parser.parse_args()

morceaux, ignores = charger_corpus([Path("sorties"), Path("sorties/archives")])
print(f"Corpus : {len(morceaux)} morceaux ({ignores} fichiers d'un ancien format ignorés)")
moteur = MoteurRecherche(morceaux, charger_encodeur(), charger_reranker())

if args.comparer:
    premiers = {}
    for mode in MODES:
        resultats = moteur.rechercher(args.question, k=args.k, marque=args.marque, mode=mode)
        premiers[mode] = resultats[0].morceau.id if resultats else None
        print(f"\n--- {mode} ---")
        for r in resultats:
            print(f"{r.score:9.4f}  {r.morceau.marque:12} {r.morceau.type:8} {r.morceau.texte[:95]}")
    if premiers["rerank"] != premiers["hybride"]:
        print("\n→ Le reranking a changé le premier résultat de la recherche hybride.")

resultats = moteur.rechercher(args.question, k=args.k, marque=args.marque)
if not args.sans_reponse:
    config = charger_config()
    reponse = repondre(
        creer_client_groq(Secrets()), config.modele, args.question, resultats, f"rag-{uuid.uuid4().hex[:8]}"
    )
    print("\n=== RÉPONSE ===")
    if reponse.information_absente:
        print("L'historique ne permet pas de répondre.")
    for a in reponse.affirmations:
        sources = ", ".join(f"{m.marque} {m.type} {m.source} du {m.date}" for m in a.sources)
        print(f"- {a.texte}  [{sources}]")
    if reponse.affirmations_retirees:
        print(f"({reponse.affirmations_retirees} phrase(s) sans source valide retirée(s))")
