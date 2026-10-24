import asyncio
import json
import logging
from dataclasses import dataclass, field
from functools import partial

import groq

from veille.llm.client import AppelOutil, ReponseLLM, appeler_llm
from veille.parallele import executer_en_parallele
from veille.tools.registre import Outil, executer_appel_outil

logger = logging.getLogger(__name__)

MESSAGE_LIMITE = (
    "Tu as atteint la limite d'appels d'outils. N'appelle plus d'outil : réponds maintenant "
    "avec les informations déjà obtenues, et signale clairement ce qui manque."
)
OBSERVATION_DOUBLON = (
    "Appel identique déjà effectué : son résultat est plus haut dans la conversation. "
    "Change d'outil ou d'arguments, ou donne ta réponse."
)
OBSERVATION_BUG = "L'outil a rencontré une erreur interne. Utilise une autre source."


@dataclass
class ResultatAgent:
    reponse: str | None
    arret: str      # "reponse_finale" ou "limite_tours"
    tours: int
    tokens: int
    messages: list[dict] = field(default_factory=list)


def message_assistant(reponse: ReponseLLM) -> dict:
    message = {"role": "assistant", "content": reponse.texte or ""}
    if reponse.appels_outils:
        message["tool_calls"] = [
            {"id": a.id, "type": "function", "function": {"name": a.nom, "arguments": a.arguments}}
            for a in reponse.appels_outils
        ]
    return message


def signature(appel: AppelOutil) -> tuple[str, str]:
    try:
        arguments = json.dumps(json.loads(appel.arguments), sort_keys=True)
    except json.JSONDecodeError:
        arguments = appel.arguments
    return (appel.nom, arguments)


def observer(
    appels: list[AppelOutil], outils: dict[str, Outil], deja_faits: set, execution_id: str
) -> list[dict]:
    nouveaux = [a for a in appels if signature(a) not in deja_faits]
    resultats = asyncio.run(executer_en_parallele([partial(executer_appel_outil, a, outils) for a in nouveaux]))
    par_id = dict(zip((a.id for a in nouveaux), resultats))

    observations = []
    for appel in appels:
        if appel.id not in par_id:
            contenu = json.dumps({"erreur": OBSERVATION_DOUBLON}, ensure_ascii=False)
        elif isinstance(par_id[appel.id], Exception):
            logger.error(json.dumps({
                "evenement": "erreur_outil", "execution_id": execution_id,
                "outil": appel.nom, "erreur": repr(par_id[appel.id]),
            }))
            contenu = json.dumps({"erreur": OBSERVATION_BUG}, ensure_ascii=False)
        else:
            contenu = par_id[appel.id]
        observations.append({"role": "tool", "tool_call_id": appel.id, "content": contenu})
        deja_faits.add(signature(appel))
    return observations


def journaliser_tour(
    execution_id: str, agent: str, tour: int, appels: list[AppelOutil], observations: list[dict]
) -> None:
    logger.info(json.dumps({
        "evenement": "tour_agent",
        "execution_id": execution_id,
        "agent": agent,
        "tour": tour,
        "appels": [
            {"outil": a.nom, "arguments": a.arguments, "apercu_observation": o["content"][:150]}
            for a, o in zip(appels, observations)
        ],
    }, ensure_ascii=False))


def terminer(resultat: ResultatAgent, execution_id: str, agent: str) -> ResultatAgent:
    logger.info(json.dumps({
        "evenement": "fin_agent",
        "execution_id": execution_id,
        "agent": agent,
        "arret": resultat.arret,
        "tours": resultat.tours,
        "tokens": resultat.tokens,
    }))
    return resultat


def executer_agent(
    client: groq.Groq,
    modele: str,
    prompt_systeme: str,
    demande: str,
    outils: dict[str, Outil],
    agent: str,
    execution_id: str,
    max_tours: int = 6,
    effort_raisonnement: str | None = None,
) -> ResultatAgent:
    messages = [{"role": "system", "content": prompt_systeme}, {"role": "user", "content": demande}]
    schemas = [outil.schema for outil in outils.values()]
    deja_faits: set[tuple[str, str]] = set()
    tokens = 0

    for tour in range(1, max_tours + 1):
        reponse = appeler_llm(
            client, modele, messages, agent, execution_id, outils=schemas, effort_raisonnement=effort_raisonnement
        )
        tokens += reponse.tokens_entree + reponse.tokens_sortie
        messages.append(message_assistant(reponse))

        if not reponse.appels_outils:
            return terminer(ResultatAgent(reponse.texte, "reponse_finale", tour, tokens, messages), execution_id, agent)

        observations = observer(reponse.appels_outils, outils, deja_faits, execution_id)
        journaliser_tour(execution_id, agent, tour, reponse.appels_outils, observations)
        messages.extend(observations)

    messages.append({"role": "user", "content": MESSAGE_LIMITE})
    # tool_choice change : Groq ne peut pas réutiliser son cache pour ce dernier appel (coût accepté, il est rare).
    reponse = appeler_llm(
        client, modele, messages, agent, execution_id, outils=schemas, choix_outil="none",
        effort_raisonnement=effort_raisonnement,
    )
    tokens += reponse.tokens_entree + reponse.tokens_sortie
    messages.append(message_assistant(reponse))
    return terminer(ResultatAgent(reponse.texte, "limite_tours", max_tours, tokens, messages), execution_id, agent)