import logging

from veille.llm.client import appeler_llm, creer_client_groq
from veille.settings import Secrets, charger_config

logging.basicConfig(level=logging.INFO, format="%(message)s")

secrets = Secrets()
config = charger_config()

client = creer_client_groq(secrets)
messages = [
    {
        "role": "user",
        "content": "Réponds en une phrase : à quoi sert la veille concurrentielle ?",
    }
]

reponse = appeler_llm(
    client, config.modele, messages, agent="essai", execution_id="test-001"
)

print(reponse.texte)
print("tokens d'entrée :", reponse.tokens_entree)
print("tokens de sortie :", reponse.tokens_sortie)
