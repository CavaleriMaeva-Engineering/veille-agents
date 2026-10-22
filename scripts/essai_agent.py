import logging
import uuid

from apify_client import ApifyClient

from veille.agents.analyste import analyser_marque
from veille.llm.client import creer_client_groq
from veille.settings import Secrets, charger_config

logging.basicConfig(level=logging.INFO, format="%(message)s")

secrets = Secrets()
config = charger_config()

rapport = analyser_marque(
    client_groq=creer_client_groq(secrets),
    client_apify=ApifyClient(secrets.apify_token.get_secret_value()),
    modele=config.modele,
    marque=config.marques[0],   # Typology
    execution_id=f"essai-{uuid.uuid4().hex[:8]}",
)

print("\n=== RAPPORT ===")
print(rapport.model_dump_json(indent=2))