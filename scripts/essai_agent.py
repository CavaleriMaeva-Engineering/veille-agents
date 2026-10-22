import logging
import uuid

from apify_client import ApifyClient

from veille.agents.boucle import executer_agent
from veille.llm.client import creer_client_groq
from veille.settings import Secrets, charger_config
from veille.tools.registre import creer_outils

logging.basicConfig(level=logging.INFO, format="%(message)s")

PROMPT_SYSTEME = """Tu es analyste en veille concurrentielle pour une marque de cosmétiques en France.
Ta mission : décrire ce qu'un concurrent met en avant dans sa publicité en ce moment.

Méthode :
- Commence par ses publicités Meta, puis TikTok. Lis une page de son site seulement si une pub renvoie vers une offre à vérifier.
- Demande peu de pubs (5 au plus sur Meta) : chaque pub a un coût.
- Si un outil renvoie une erreur, ne t'acharne pas : passe à une autre source et signale-le.
- N'invente rien : chaque affirmation doit venir d'un résultat d'outil.

Réponse finale, en français, en 5 à 8 puces :
produits poussés, messages et promesses, offres, formats et plateformes, cible, et ce qui manque."""

secrets = Secrets()
config = charger_config()
marque = config.marques[0]   # Typology

client_groq = creer_client_groq(secrets)
client_apify = ApifyClient(secrets.apify_token.get_secret_value())
outils = creer_outils(client_apify)

resultat = executer_agent(
    client=client_groq,
    modele=config.modele,
    prompt_systeme=PROMPT_SYSTEME,
    demande=f"Fais la veille publicitaire de {marque.nom} (site : {marque.site}).",
    outils=outils,
    agent="analyste",
    execution_id=f"essai-{uuid.uuid4().hex[:8]}",
    max_tours=5,
)

print("\n=== RÉSULTAT ===")
print(f"Arrêt : {resultat.arret} | tours : {resultat.tours} | tokens : {resultat.tokens}")
print(resultat.reponse)