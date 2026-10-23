import json
import logging
from collections.abc import Callable
from datetime import date, datetime

import groq
from apify_client import ApifyClient
from pydantic import BaseModel

from veille.agents.analyste import (
    AnalyseMarque,
    Collecte,
    collecter_marque,
    rediger_analyse,
)
from veille.agents.changements import comparer
from veille.agents.memoire import Rappel, formater_memoire, requete_depuis_collecte
from veille.agents.rapport import RapportVeille
from veille.agents.signaux import SOURCE_PAR_OUTIL, Signaux
from veille.garde_fous import verifier_ancrage
from veille.settings import Config, Marque
from veille.storage.analyses import charger_derniere_analyse, enregistrer_analyse

logger = logging.getLogger(__name__)

MAX_COLLECTES = 2   # une relance au plus : chaque collecte coûte des crédits Apify et des tokens
OUTILS_DE_PUBS = ["chercher_pubs_meta", "chercher_pubs_tiktok"]
SOURCES_DE_PUBS = {SOURCE_PAR_OUTIL[outil] for outil in OUTILS_DE_PUBS}


class ResultatVeille(BaseModel):
    analyses: list[AnalyseMarque]
    echecs: dict[str, str]   # marque -> cause de l'échec


def raisons_de_relancer(signaux: Signaux, outils_actifs: list[str] | None) -> list[str]:
    """Pourquoi la collecte est insuffisante ; liste vide si elle est exploitable.

    0 pub SANS erreur n'est pas une raison : la marque ne fait simplement pas de pub.
    Une page du site en erreur non plus : elle complète, elle n'est pas indispensable.
    """
    raisons = [f"{source} en erreur" for source in signaux.sources_en_erreur if source in SOURCES_DE_PUBS]
    outils = OUTILS_DE_PUBS if outils_actifs is None else [o for o in outils_actifs if o in OUTILS_DE_PUBS]
    for outil in outils:
        source = SOURCE_PAR_OUTIL[outil]
        if source not in signaux.sources_interrogees:
            raisons.append(f"{source} jamais interrogée")   # l'agent a oublié un outil
    return raisons


def traiter_marque(
    marque: Marque,
    config: Config,
    client_groq: groq.Groq,
    client_apify: ApifyClient,
    id_marque: str,
    collecter: Callable[..., Collecte],
    rediger: Callable[..., RapportVeille],
    charger_precedente: Callable[[str], AnalyseMarque | None],
    rappeler: Rappel | None = None,
) -> AnalyseMarque:
    # Décision 1 : relancer une collecte insuffisante, au plus MAX_COLLECTES fois en tout.
    for nb_collectes in range(1, MAX_COLLECTES + 1):
        collecte = collecter(
            client_groq=client_groq, client_apify=client_apify, modele=config.modele,
            marque=marque, execution_id=id_marque, outils_actifs=config.outils_actifs,
        )
        raisons = raisons_de_relancer(collecte.signaux, config.outils_actifs)
        if not raisons:
            break
        logger.warning(json.dumps({
            "evenement": "collecte_insuffisante", "execution_id": id_marque, "marque": marque.nom,
            "collecte": nb_collectes, "raisons": raisons, "relance": nb_collectes < MAX_COLLECTES,
        }, ensure_ascii=False))

    # Décision 2 : ne rédiger (appel LLM) que s'il y a du nouveau depuis la veille précédente.
    # La précédente se charge avant l'enregistrement, sinon on se comparerait à soi-même.
    precedente = charger_precedente(marque.nom)
    changements = comparer(collecte.signaux, precedente.signaux if precedente else None)
    souvenirs, alertes = [], list(collecte.incidents)
    if precedente is not None and not changements.significatif:
        rapport, decision = precedente.rapport, "reutilise"
    else:
        # Mémoire long terme : seulement quand on rédige (inutile de chercher dans le passé pour rien).
        memoire = None
        if rappeler is not None:
            souvenirs = rappeler(marque.nom, requete_depuis_collecte(collecte.observations, marque.nom))
            memoire = formater_memoire(souvenirs, changements)
        rapport = rediger(
            client_groq=client_groq, modele=config.modele, marque=marque.nom,
            collecte=collecte, execution_id=id_marque, memoire=memoire,
        )
        decision = "redige"
        # Garde-fou de sortie : chaque chiffre d'un constat doit venir des données (ou de la mémoire).
        rapport, retires = verifier_ancrage(rapport, collecte.observations, collecte.signaux, memoire)
        alertes += retires
    logger.info(json.dumps({
        "evenement": "decision_rapport", "execution_id": id_marque, "marque": marque.nom,
        "decision": decision, "comparable": changements.comparable, "score": changements.score,
        "significatif": changements.significatif, "nb_collectes": nb_collectes,
        "nb_souvenirs": len(souvenirs), "nb_alertes": len(alertes),
    }, ensure_ascii=False))

    return AnalyseMarque(
        marque=marque.nom, date=date.today(), horodatage=datetime.now(), execution_id=id_marque,
        observations=collecte.observations, signaux=collecte.signaux, rapport=rapport,
        changements=changements, decision=decision, nb_collectes=nb_collectes,
        souvenirs=[s.id for s in souvenirs], alertes=alertes, trajectoire=collecte.trajectoire,
    )


def lancer_veille(
    config: Config,
    client_groq: groq.Groq,
    client_apify: ApifyClient,
    execution_id: str,
    collecter: Callable[..., Collecte] = collecter_marque,
    rediger: Callable[..., RapportVeille] = rediger_analyse,
    enregistrer: Callable[[AnalyseMarque], object] = enregistrer_analyse,
    charger_precedente: Callable[[str], AnalyseMarque | None] = charger_derniere_analyse,
    rappeler: Rappel | None = None,
) -> ResultatVeille:
    analyses, echecs = [], {}
    for marque in config.marques:
        id_marque = f"{execution_id}-{marque.nom.lower().replace(' ', '-')}"
        try:
            analyse = traiter_marque(
                marque, config, client_groq, client_apify, id_marque, collecter, rediger, charger_precedente,
                rappeler,
            )
        except Exception as erreur:  # noqa: BLE001 — cloison : une marque en échec ne doit pas arrêter les autres
            logger.error(json.dumps({
                "evenement": "echec_marque", "execution_id": id_marque,
                "marque": marque.nom, "erreur": repr(erreur),
            }, ensure_ascii=False))
            echecs[marque.nom] = repr(erreur)
            continue
        enregistrer(analyse)
        analyses.append(analyse)
    return ResultatVeille(analyses=analyses, echecs=echecs)
