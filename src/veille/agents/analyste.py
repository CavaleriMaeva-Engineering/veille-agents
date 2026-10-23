import json
import logging
from datetime import date, datetime
from typing import Literal

import groq
from apify_client import ApifyClient
from pydantic import BaseModel, Field

from veille.agents.boucle import executer_agent
from veille.agents.changements import Changements
from veille.agents.rapport import (
    RapportVeille,
    extraire_observations,
    rediger_rapport,
    verifier_sources,
)
from veille.agents.signaux import Signaux, calculer_signaux, extraire_resultats
from veille.garde_fous import Garde
from veille.settings import Marque
from veille.tools.registre import creer_outils

logger = logging.getLogger(__name__)

PROMPT_COLLECTE = """Tu es chargé de COLLECTER des données de veille publicitaire sur une marque de cosmétiques en France.
Tu ne rédiges pas de rapport : une autre étape s'en chargera à partir des résultats de tes outils.

Méthode, avec les seuls outils qui te sont fournis :
1. Cherche ses publicités Meta avec le domaine de son site (5 au plus : chaque pub a un coût).
2. Si l'outil chercher_pubs_tiktok t'est fourni, cherche ses publicités TikTok avec le domaine de son site.
3. Si une pub renvoie vers une offre précise (prix, coffret, promotion), lis cette page de son site. Une seule page suffit.
N'appelle jamais un outil qui ne t'est pas fourni. Si un outil renvoie une erreur, ne le relance pas.

Quand les étapes sont faites, réponds seulement « Collecte terminée »."""


class Collecte(BaseModel):
    observations: list[str]  # données brutes renvoyées par les outils
    signaux: Signaux         # calculés par le code à partir de ces données
    incidents: list[str] = Field(default_factory=list)   # garde-fous déclenchés pendant la collecte


class AnalyseMarque(BaseModel):
    marque: str
    date: date
    horodatage: datetime   # instant précis : départage plusieurs analyses du même jour
    execution_id: str
    observations: list[str]  # données brutes de la collecte, pour pouvoir rejouer la rédaction
    signaux: Signaux
    rapport: RapportVeille
    changements: Changements | None = None   # calculé par le superviseur, None pour les anciennes analyses
    decision: Literal["redige", "reutilise"] = "redige"   # rapport rédigé, ou repris faute de nouveauté
    nb_collectes: int = 1                    # 2 si le superviseur a relancé la collecte
    souvenirs: list[str] = Field(default_factory=list)   # morceaux d'historique montrés au rédacteur (traçabilité)
    alertes: list[str] = Field(default_factory=list)     # garde-fous déclenchés (collecte et ancrage) : baissent la confiance


def collecter_marque(
    client_groq: groq.Groq,
    client_apify: ApifyClient,
    modele: str,
    marque: Marque,
    execution_id: str,
    max_tours: int = 5,
    outils_actifs: list[str] | None = None,
) -> Collecte:
    """Agent collecteur : il a les outils, mais aucune consigne de rédaction. Ses outils sont encadrés par une Garde."""
    garde = Garde(marque=marque, execution_id=execution_id)
    resultat = executer_agent(
        client=client_groq,
        modele=modele,
        prompt_systeme=PROMPT_COLLECTE,
        demande=f"Marque : {marque.nom}. Site : {marque.site}.",
        outils=garde.proteger(creer_outils(client_apify, outils_actifs)),
        agent="collecteur",
        execution_id=execution_id,
        max_tours=max_tours,
    )
    return Collecte(
        observations=extraire_observations(resultat.messages),
        signaux=calculer_signaux(extraire_resultats(resultat.messages)),
        incidents=garde.incidents,
    )


def rediger_analyse(
    client_groq: groq.Groq,
    modele: str,
    marque: str,
    collecte: Collecte,
    execution_id: str,
    memoire: str | None = None,
) -> RapportVeille:
    """Agent rédacteur : aucun outil, il ne voit que les données collectées, les signaux et sa mémoire."""
    rapport = rediger_rapport(
        client_groq, modele, marque, collecte.observations, collecte.signaux, execution_id, memoire=memoire
    )
    rapport, nb_retirees = verifier_sources(rapport, collecte.signaux.sources_collectees)
    if nb_retirees:
        logger.warning(json.dumps({
            "evenement": "sources_inventees_retirees", "execution_id": execution_id,
            "marque": marque, "nb": nb_retirees,
        }))
    return rapport


def analyser_marque(
    client_groq: groq.Groq,
    client_apify: ApifyClient,
    modele: str,
    marque: Marque,
    execution_id: str,
    max_tours: int = 5,
    outils_actifs: list[str] | None = None,
) -> AnalyseMarque:
    """Collecte puis rédaction, sans aucune décision : pour les essais (scripts/essai_agent.py)."""
    collecte = collecter_marque(client_groq, client_apify, modele, marque, execution_id, max_tours, outils_actifs)
    rapport = rediger_analyse(client_groq, modele, marque.nom, collecte, execution_id)
    return AnalyseMarque(
        marque=marque.nom, date=date.today(), horodatage=datetime.now(), execution_id=execution_id,
        observations=collecte.observations, signaux=collecte.signaux, rapport=rapport,
    )
