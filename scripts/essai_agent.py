import logging
import uuid

from apify_client import ApifyClient

from veille.agents.analyste import analyser_marque
from veille.llm.client import creer_client_groq
from veille.settings import Secrets, charger_config
from veille.storage.analyses import enregistrer_analyse

logging.basicConfig(level=logging.INFO, format="%(message)s")

secrets = Secrets()
config = charger_config()

analyse = analyser_marque(
    client_groq=creer_client_groq(secrets),
    client_apify=ApifyClient(secrets.apify_token.get_secret_value()),
    modele=config.modele,
    marque=config.marques[0],   # Typology
    execution_id=f"essai-{uuid.uuid4().hex[:8]}",
)

print("\n=== ANALYSE ===")
print(analyse.model_dump_json(indent=2))

chemin = enregistrer_analyse(analyse)
print(f"\nAnalyse enregistrée : {chemin}")