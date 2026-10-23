"""Lancer toutes les évaluations et écrire un rapport dans evals/resultats/.

    uv run python scripts/evaluer.py               # recherche + rédacteur + agent (gratuit, sans LLM)
    uv run python scripts/evaluer.py --reponses    # + réponses du RAG avec Groq (abstention, citations)
"""

import argparse
import json
import logging
import uuid
from datetime import datetime

from pydantic import ValidationError

from veille.agents.analyste import AnalyseMarque
from veille.evals.metriques import moyenne
from veille.evals.production import evaluer_redactions, evaluer_trajectoires, tableau
from veille.evals.rag import (
    DOSSIER_EVALS,
    charger_annotations,
    charger_cas,
    evaluer_recherche,
)
from veille.llm.client import creer_client_groq
from veille.rag.documents import charger_corpus
from veille.rag.modeles import charger_encodeur, charger_reranker
from veille.rag.recherche import MODES, MoteurRecherche
from veille.rag.reponse import repondre
from veille.settings import Secrets, charger_config
from veille.storage.analyses import DOSSIER_SORTIES

logging.basicConfig(level=logging.WARNING, format="%(message)s")
parser = argparse.ArgumentParser()
parser.add_argument("-k", type=int, default=5)
parser.add_argument("--reponses", action="store_true", help="évaluer aussi les réponses (appels Groq)")
args = parser.parse_args()

dossiers = [DOSSIER_SORTIES, DOSSIER_SORTIES / "archives"]
analyses = []
for dossier in dossiers:
    for chemin in sorted(dossier.glob("*.json")):
        if "_synthese-marche_" in chemin.name:
            continue
        try:
            analyses.append(AnalyseMarque.model_validate_json(chemin.read_text(encoding="utf-8")))
        except ValidationError:
            pass

cas, annotations = charger_cas(), charger_annotations()
morceaux, _ = charger_corpus(dossiers)
moteur = MoteurRecherche(morceaux, charger_encodeur(), charger_reranker())
scores_rag, details = evaluer_recherche(moteur, cas, annotations, list(MODES), k=args.k)

sections = [
    f"# Évaluations du {datetime.now():%d/%m/%Y %H:%M}",
    f"Corpus : {len(morceaux)} morceaux · {len(analyses)} analyses · {len(annotations)} / {len(cas)} cas annotés.",
    f"## Recherche (k = {args.k}, cas annotés avec au moins un pertinent)", tableau(scores_rag),
    "## Rédacteur (vraies veilles)", tableau([evaluer_redactions(analyses)]),
    "## Agent collecteur (veilles avec trajectoire)", tableau([evaluer_trajectoires(analyses)]),
]

if args.reponses:
    client, modele = creer_client_groq(Secrets()), charger_config().modele
    lignes, ok_abstention, ok_reponse, retirees = [], [], [], 0
    for c in cas:
        resultats = moteur.rechercher(c.question, k=args.k, marque=c.marque)
        reponse = repondre(client, modele, c.question, resultats, f"eval-{uuid.uuid4().hex[:6]}")
        retirees += reponse.affirmations_retirees
        if c.attendu == "abstention":
            ok_abstention.append(1.0 if reponse.information_absente else 0.0)
        else:
            ok_reponse.append(0.0 if reponse.information_absente else 1.0)
        lignes.append(f"| {c.id} | {c.attendu} | {'abstention' if reponse.information_absente else 'réponse'} | "
                      f"{' / '.join(a.texte for a in reponse.affirmations)[:160]} |")
    sections += [
        "## Réponses (Groq)",
        (
            f"Abstention correcte (cas adverses) : {moyenne(ok_abstention):.0%} · "
            f"réponse fournie (cas avec réponse) : {moyenne(ok_reponse):.0%} · phrases sans source retirées : {retirees}"
        ),
        "| cas | attendu | obtenu | réponse |\n| --- | --- | --- | --- |\n" + "\n".join(lignes),
    ]

rapport = "\n\n".join(sections)
sortie = DOSSIER_EVALS / "resultats"
sortie.mkdir(parents=True, exist_ok=True)
horodatage = f"{datetime.now():%Y-%m-%dT%H-%M}"
(sortie / f"{horodatage}.md").write_text(rapport, encoding="utf-8")
(sortie / f"{horodatage}_details.json").write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
print(rapport)
print(f"\nRapport : {sortie / f'{horodatage}.md'}")
