import json
import logging
import time

import groq
from pydantic import BaseModel

from veille.reseau import appeler_avec_tentatives
from veille.settings import Secrets

logger = logging.getLogger(__name__)


class ReponseLLM(BaseModel):
    texte: str
    tokens_entree: int
    tokens_sortie: int


def creer_client_groq(secrets: Secrets) -> groq.Groq:
    return groq.Groq(
        api_key=secrets.groq_api_key.get_secret_value(),
        timeout=60.0,
        max_retries=0,
    )


def appeler_llm(
    client: groq.Groq,
    modele: str,
    messages: list[dict],
    agent: str,
    execution_id: str,
) -> ReponseLLM:
    tentative = 0

    def appel():
        nonlocal tentative
        tentative += 1
        debut = time.perf_counter()  # avant le try : existe toujours
        try:
            reponse = client.chat.completions.create(model=modele, messages=messages)
        except Exception as erreur:
            logger.warning(
                json.dumps(
                    {
                        "evenement": "appel_llm",
                        "execution_id": execution_id,
                        "agent": agent,
                        "modele": modele,
                        "tentative": tentative,
                        "statut": "echec",
                        "latence_ms": round(
                            (time.perf_counter() - debut) * 1000
                        ),  # calculée ici
                        "tokens_entree": None,  # pas de réponse, donc pas de tokens
                        "tokens_sortie": None,
                        "erreur": str(erreur),
                    }
                )
            )
            raise  # la boucle décide de réessayer ou non
        logger.info(
            json.dumps(
                {
                    "evenement": "appel_llm",
                    "execution_id": execution_id,
                    "agent": agent,
                    "modele": modele,
                    "tentative": tentative,
                    "statut": "succes",
                    "latence_ms": round((time.perf_counter() - debut) * 1000),
                    "tokens_entree": reponse.usage.prompt_tokens,
                    "tokens_sortie": reponse.usage.completion_tokens,
                    "erreur": None,
                }
            )
        )
        return reponse

    reponse = appeler_avec_tentatives(appel)
    return ReponseLLM(
        texte=reponse.choices[0].message.content,
        tokens_entree=reponse.usage.prompt_tokens,
        tokens_sortie=reponse.usage.completion_tokens,
    )
