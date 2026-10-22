from datetime import date

import groq
from apify_client import ApifyClient
from pydantic import BaseModel

from veille.agents.boucle import executer_agent
from veille.agents.rapport import RapportVeille, extraire_observations, rediger_rapport
from veille.agents.signaux import Signaux, calculer_signaux, extraire_resultats
from veille.settings import Marque
from veille.tools.registre import creer_outils

PROMPT_COLLECTE = """Tu es chargé de COLLECTER des données de veille publicitaire sur une marque de cosmétiques en France.
Tu ne rédiges pas de rapport : une autre étape s'en chargera à partir des résultats de tes outils.

Méthode :
1. Cherche ses publicités Meta (5 au plus : chaque pub a un coût).
2. Cherche ses publicités TikTok, avec le domaine de son site.
3. Si une pub renvoie vers une offre précise (prix, coffret, promotion), lis cette page de son site. Une seule page suffit.
Utilise uniquement les outils fournis : lire_page_web, chercher_pubs_meta, chercher_pubs_tiktok.
Si un outil renvoie une erreur, ne le relance pas : passe à l'étape suivante.

Quand les étapes sont faites, réponds seulement « Collecte terminée »."""


class AnalyseMarque(BaseModel):
    marque: str
    date: date
    execution_id: str
    signaux: Signaux
    rapport: RapportVeille


def analyser_marque(
    client_groq: groq.Groq,
    client_apify: ApifyClient,
    modele: str,
    marque: Marque,
    execution_id: str,
    max_tours: int = 5,
) -> AnalyseMarque:
    collecte = executer_agent(
        client=client_groq,
        modele=modele,
        prompt_systeme=PROMPT_COLLECTE,
        demande=f"Marque : {marque.nom}. Site : {marque.site}.",
        outils=creer_outils(client_apify),
        agent="collecteur",
        execution_id=execution_id,
        max_tours=max_tours,
    )
    signaux = calculer_signaux(extraire_resultats(collecte.messages))
    rapport = rediger_rapport(
        client_groq, modele, marque.nom, extraire_observations(collecte.messages), signaux, execution_id
    )
    return AnalyseMarque(
        marque=marque.nom, date=date.today(), execution_id=execution_id, signaux=signaux, rapport=rapport
    )
