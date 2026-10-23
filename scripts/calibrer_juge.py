"""Calibrer le LLM juge : mesurer son accord avec tes annotations humaines.

    uv run python scripts/calibrer_juge.py --cas 3    # essai rapide sur 3 questions
    uv run python scripts/calibrer_juge.py            # les 26 questions : ≈ 52 appels Groq, 10 à 15 min (limite de débit)

Le juge voit exactement les mêmes candidats que toi lors de l'annotation (même pooling), avec les mêmes règles.
"""

import argparse
import json
import logging
from datetime import datetime

from veille.evals.juge import (
    Paire,
    journaliser_desaccords,
    juger_deux_ordres,
    mesurer_accord,
)
from veille.evals.production import tableau
from veille.evals.rag import (
    DOSSIER_EVALS,
    charger_annotations,
    charger_cas,
    pool_candidats,
)
from veille.llm.client import creer_client_groq
from veille.rag.documents import charger_corpus
from veille.rag.modeles import charger_encodeur, charger_reranker
from veille.rag.recherche import MoteurRecherche
from veille.settings import Secrets, charger_config
from veille.storage.analyses import DOSSIER_SORTIES

logging.basicConfig(level=logging.WARNING, format="%(message)s")
parser = argparse.ArgumentParser()
parser.add_argument("--cas", type=int, help="ne juger que les N premières questions (essai)")
parser.add_argument("--max-extraits", type=int, default=14, help="extraits jugés par question (débit Groq)")
args = parser.parse_args()

cas, annotations = charger_cas(), charger_annotations()
cas = [c for c in cas if c.id in annotations][: args.cas]
morceaux, _ = charger_corpus([DOSSIER_SORTIES, DOSSIER_SORTIES / "archives"])
par_id = {m.id: m for m in morceaux}
moteur = MoteurRecherche(morceaux, charger_encodeur(), charger_reranker())
client, modele = creer_client_groq(Secrets()), charger_config().modele

paires: list[Paire] = []
for numero, c in enumerate(cas, start=1):
    annotation = annotations[c.id]
    if annotation.candidats:   # annotations récentes : les candidats exacts sont enregistrés
        candidats = [par_id[i] for i in annotation.candidats if i in par_id]
    else:                      # annotations plus anciennes : même pooling, même corpus, donc mêmes candidats
        candidats = pool_candidats(moteur, c)
    pertinents = set(annotation.pertinents)
    retenus = candidats[: args.max_extraits]
    retenus += [m for m in candidats[args.max_extraits:] if m.id in pertinents]   # ne jamais perdre un pertinent

    verdicts = juger_deux_ordres(
        client, modele, c.question, [f"[{m.marque} · {m.type} · {m.date}] {m.texte}" for m in retenus], f"juge-{c.id}"
    )
    for m, (endroit, envers) in zip(retenus, verdicts, strict=True):
        paires.append(Paire(cas=c.id, morceau=m.id, longueur=len(m.texte), humain=m.id in pertinents,
                            endroit=endroit, envers=envers))
    print(f"{numero}/{len(cas)} {c.id} jugée ({len(retenus)} extraits)", flush=True)

journaliser_desaccords(paires)
accord = mesurer_accord(paires)
textes = {m.id: m.texte for m in morceaux}
desaccords = [p for p in paires if p.coherent and p.endroit != p.humain]
instables = [p for p in paires if p.endroit is not None and p.envers is not None and not p.coherent]

lignes_desaccords = "\n".join(
    f"| {p.cas} | {'oui' if p.humain else 'non'} | {'oui' if p.endroit else 'non'} | {textes.get(p.morceau, '')} |"
    for p in desaccords
)
rapport = "\n\n".join([
    f"# Calibration du juge du {datetime.now():%d/%m/%Y %H:%M}",
    f"Modèle juge : {modele} · {len(cas)} questions · {accord.nb_paires} paires (question, extrait).",
    tableau([accord]),
    "Repères pour le kappa : < 0,4 faible · 0,4 à 0,6 modéré · 0,6 à 0,8 substantiel · > 0,8 excellent.",
    f"## Désaccords ({len(desaccords)}) : humain · juge · extrait",
    "| cas | humain | juge | extrait |\n| --- | --- | --- | --- |\n" + lignes_desaccords if desaccords else "Aucun.",
    f"## Verdicts instables selon l'ordre : {len(instables)} · extraits oubliés par le juge : {accord.nb_non_jugees}",
])
sortie = DOSSIER_EVALS / "resultats"
sortie.mkdir(parents=True, exist_ok=True)
horodatage = f"{datetime.now():%Y-%m-%dT%H-%M}"
(sortie / f"{horodatage}_juge.md").write_text(rapport, encoding="utf-8")
(sortie / f"{horodatage}_juge_paires.json").write_text(
    json.dumps([p.model_dump() for p in paires], ensure_ascii=False, indent=2), encoding="utf-8"
)
print("\n" + rapport + f"\n\nRapport : {sortie / f'{horodatage}_juge.md'}")
