import logging
import uuid

from apify_client import ApifyClient

from veille.agents.superviseur import lancer_veille
from veille.llm.client import creer_client_groq
from veille.settings import Secrets, charger_config

logging.basicConfig(level=logging.INFO, format="%(message)s")

secrets = Secrets()
config = charger_config()

resultat = lancer_veille(
    config,
    creer_client_groq(secrets),
    ApifyClient(secrets.apify_token.get_secret_value()),
    execution_id=f"veille-{uuid.uuid4().hex[:8]}",
)

print("\n=== BILAN DE LA VEILLE ===")
for analyse in resultat.analyses:
    durable = analyse.signaux.pub_la_plus_durable
    gagnante = f"{durable.duree_jours} j ({durable.source})" if durable else "aucune"
    score = analyse.changements.score if analyse.changements and analyse.changements.comparable else "-"
    print(
        f"{analyse.marque:15} pubs {analyse.signaux.nb_pubs}  pub la plus durable : {gagnante}  "
        f"rapport {analyse.decision} (changement {score}, {analyse.nb_collectes} collecte(s))"
    )
for marque, erreur in resultat.echecs.items():
    print(f"{marque:15} ÉCHEC : {erreur}")