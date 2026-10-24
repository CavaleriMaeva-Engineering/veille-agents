import json
import logging
import time

import groq
from pydantic import BaseModel, Field

from veille.couts import cout_groq
from veille.reseau import appeler_avec_tentatives
from veille.settings import Secrets
from veille.traces import span

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
    tokens_caches: int = 0          # part de tokens_entree lue dans le cache de Groq (facturée moitié prix)
    tokens_raisonnement: int = 0    # part de tokens_sortie passée à raisonner (facturée comme de la sortie)


def detail_usage(usage, groupe: str, champ: str) -> int:
    """Lit usage.<groupe>.<champ> s'il existe : tous les modèles ne renvoient pas ces détails."""
    valeur = getattr(getattr(usage, groupe, None), champ, None)
    return valeur if isinstance(valeur, int) else 0


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
            # Un span par tentative : une tentative en échec (429, 5xx) coûte du temps, et on veut la voir.
            with span("llm", modele, agent=agent, modele=modele, tentative=tentative,
                      execution_id=execution_id, effort=effort_raisonnement, nb_outils=len(outils or [])) as attributs:
                reponse = client.chat.completions.create(**parametres)
                usage = reponse.usage
                caches = detail_usage(usage, "prompt_tokens_details", "cached_tokens")
                attributs.update(
                    tokens_entree=usage.prompt_tokens,
                    tokens_caches=caches,
                    tokens_sortie=usage.completion_tokens,
                    tokens_raisonnement=detail_usage(usage, "completion_tokens_details", "reasoning_tokens"),
                    cout_usd=cout_groq(modele, usage.prompt_tokens, caches, usage.completion_tokens),
                )
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
                    "tokens_caches": detail_usage(reponse.usage, "prompt_tokens_details", "cached_tokens"),
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
        tokens_caches=detail_usage(reponse.usage, "prompt_tokens_details", "cached_tokens"),
        tokens_raisonnement=detail_usage(reponse.usage, "completion_tokens_details", "reasoning_tokens"),
    )
