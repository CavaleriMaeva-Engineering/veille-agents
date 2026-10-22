import json
import logging
import time

import groq
from pydantic import BaseModel, Field

from veille.reseau import appeler_avec_tentatives
from veille.settings import Secrets

logger = logging.getLogger(__name__)


class AppelOutil(BaseModel):
    id: str
    nom: str
    arguments: str # JSON brut écrit par le LLM, validé plus tard avec le modèle Args de l'outil


class ReponseLLM(BaseModel):
    texte: str | None  # None quand le LLM ne fait que demander des outils
    appels_outils: list[AppelOutil] = Field(default_factory=list)
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
    outils: list[dict] | None = None,
    choix_outil: str | None = None,
    format_reponse: dict | None = None,
    max_tokens_sortie: int | None = None,
    effort_raisonnement: str | None = None,
) -> ReponseLLM:
    tentative = 0

    def appel():
        nonlocal tentative
        tentative += 1
        debut = time.perf_counter()  # avant le try : existe toujours
        parametres = {"model": modele, "messages": messages}
        if outils:
            parametres["tools"] = outils
            parametres["tool_choice"] = choix_outil or "auto"
        if format_reponse:
            parametres["response_format"] = format_reponse
        if max_tokens_sortie:
            parametres["max_completion_tokens"] = max_tokens_sortie
        if effort_raisonnement:
            parametres["reasoning_effort"] = effort_raisonnement
        try:
            reponse = client.chat.completions.create(**parametres)
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
    message = reponse.choices[0].message
    return ReponseLLM(
        texte=message.content,
        appels_outils=[
            AppelOutil(id=a.id, nom=a.function.name, arguments=a.function.arguments)
            for a in (message.tool_calls or [])
        ],
        tokens_entree=reponse.usage.prompt_tokens,
        tokens_sortie=reponse.usage.completion_tokens,
    )
