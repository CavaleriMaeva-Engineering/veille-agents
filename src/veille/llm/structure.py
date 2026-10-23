import groq
from pydantic import BaseModel, ValidationError

from veille.llm.client import appeler_llm
from veille.tools.registre import resumer_erreurs


def format_json_strict(modele: type[BaseModel]) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {"name": modele.__name__, "strict": True, "schema": modele.model_json_schema()},
    }


def est_echec_de_schema(erreur: groq.BadRequestError) -> bool:
    corps = erreur.body if isinstance(erreur.body, dict) else {}
    details = corps.get("error", corps)
    return isinstance(details, dict) and details.get("code") == "json_validate_failed"


def generer_structure[T: BaseModel](
    client: groq.Groq,
    modele: str,
    messages: list[dict],
    modele_sortie: type[T],
    agent: str,
    execution_id: str,
    max_essais: int = 2,
) -> T:
    messages = list(messages)   # copie : on n'ajoute pas nos corrections dans la liste de l'appelant
    for essai in range(1, max_essais + 1):
        # 1. Appel au LLM : le serveur peut refuser une réponse hors schéma (400 json_validate_failed)
        try:
            reponse = appeler_llm(
                client, modele, messages, agent=agent, execution_id=execution_id,
                format_reponse=format_json_strict(modele_sortie),
                max_tokens_sortie=4096,
                effort_raisonnement="low",
            )
        except groq.BadRequestError as erreur:
            if not est_echec_de_schema(erreur) or essai == max_essais:
                raise
            messages.append({
                "role": "user",
                "content": "Ta réponse précédente a été refusée car elle ne respectait pas le schéma. "
                "Réponds avec UN SEUL objet JSON conforme au schéma, sans tableau autour.",
            })
            continue

        # 2. Validation de notre côté : Pydantic peut refuser une réponse que le serveur a acceptée
        try:
            return modele_sortie.model_validate_json(reponse.texte or "")
        except ValidationError as erreur:
            if essai == max_essais:
                raise
            messages.append({"role": "assistant", "content": reponse.texte or ""})
            messages.append({
                "role": "user",
                "content": f"Ton JSON ne respecte pas le format : {resumer_erreurs(erreur)}. Corrige-le.",
            })