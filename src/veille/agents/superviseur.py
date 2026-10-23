import json
import logging
from collections.abc import Callable

import groq
from apify_client import ApifyClient
from pydantic import BaseModel

from veille.agents.analyste import AnalyseMarque, analyser_marque
from veille.agents.changements import comparer
from veille.settings import Config
from veille.storage.analyses import charger_derniere_analyse, enregistrer_analyse

logger = logging.getLogger(__name__)


class ResultatVeille(BaseModel):
    analyses: list[AnalyseMarque]
    echecs: dict[str, str]   # marque -> cause de l'échec


def lancer_veille(
    config: Config,
    client_groq: groq.Groq,
    client_apify: ApifyClient,
    execution_id: str,
    analyser: Callable[..., AnalyseMarque] = analyser_marque,
    enregistrer: Callable[[AnalyseMarque], object] = enregistrer_analyse,
    charger_precedente: Callable[[str], AnalyseMarque | None] = charger_derniere_analyse,
) -> ResultatVeille:
    analyses, echecs = [], {}
    for marque in config.marques:
        id_marque = f"{execution_id}-{marque.nom.lower().replace(' ', '-')}"
        try:
            analyse = analyser(
                client_groq=client_groq, client_apify=client_apify, modele=config.modele,
                marque=marque, execution_id=id_marque, outils_actifs=config.outils_actifs,
            )
        except Exception as erreur:  # noqa: BLE001 — cloison : une marque en échec ne doit pas arrêter les autres
            logger.error(json.dumps({
                "evenement": "echec_marque", "execution_id": id_marque,
                "marque": marque.nom, "erreur": repr(erreur),
            }, ensure_ascii=False))
            echecs[marque.nom] = repr(erreur)
            continue
        precedente = charger_precedente(marque.nom)
        analyse.changements = comparer(analyse.signaux, precedente.signaux if precedente else None)
        logger.info(json.dumps({
            "evenement": "changements", "execution_id": id_marque, "marque": marque.nom,
            "comparable": analyse.changements.comparable, "score": analyse.changements.score,
            "significatif": analyse.changements.significatif,
        }, ensure_ascii=False))
        enregistrer(analyse)
        analyses.append(analyse)
    return ResultatVeille(analyses=analyses, echecs=echecs)