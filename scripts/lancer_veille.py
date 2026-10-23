import argparse
import logging
import uuid
from pathlib import Path

from apify_client import ApifyClient

from veille.agents.memoire import construire_rappel
from veille.agents.superviseur import lancer_veille
from veille.llm.client import creer_client_groq
from veille.rag.modeles import charger_encodeur
from veille.settings import Secrets, charger_config

logging.basicConfig(level=logging.INFO, format="%(message)s")

parser = argparse.ArgumentParser(description="Lancer une veille complète")
parser.add_argument("--sans-memoire", action="store_true", help="ne pas charger l'historique (plus rapide)")
args = parser.parse_args()

secrets = Secrets()
config = charger_config()
# Mémoire construite AVANT la veille : elle ne contient que les veilles passées.
rappeler = None if args.sans_memoire else construire_rappel([Path("sorties"), Path("sorties/archives")], charger_encodeur())

resultat = lancer_veille(
    config,
    creer_client_groq(secrets),
    ApifyClient(secrets.apify_token.get_secret_value()),
    execution_id=f"veille-{uuid.uuid4().hex[:8]}",
    rappeler=rappeler,
)

print("\n=== BILAN DE LA VEILLE ===")
for analyse in resultat.analyses:
    durable = analyse.signaux.pub_la_plus_durable
    gagnante = f"{durable.duree_jours} j ({durable.source})" if durable else "aucune"
    score = analyse.changements.score if analyse.changements and analyse.changements.comparable else "-"
    print(
        f"{analyse.marque:15} pubs {analyse.signaux.nb_pubs}  pub la plus durable : {gagnante}  "
        f"rapport {analyse.decision} (changement {score}, {analyse.nb_collectes} collecte(s), "
        f"{len(analyse.souvenirs)} souvenir(s))"
    )
for marque, erreur in resultat.echecs.items():
    print(f"{marque:15} ÉCHEC : {erreur}")