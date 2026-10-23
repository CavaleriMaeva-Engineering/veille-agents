import json
from types import SimpleNamespace
from unittest.mock import Mock

import groq
import httpx
import pytest
from pydantic import BaseModel

from veille.llm.structure import generer_structure


class Petit(BaseModel):
    nom: str


def erreur_400(code: str) -> groq.BadRequestError:
    reponse = httpx.Response(400, request=httpx.Request("POST", "https://exemple.test"))
    return groq.BadRequestError("refus", response=reponse, body={"error": {"code": code}})


def reponse_groq(contenu: str):
    message = SimpleNamespace(content=contenu, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


def test_echec_de_schema_cote_serveur_reessaye():
    client = Mock()
    client.chat.completions.create.side_effect = [erreur_400("json_validate_failed"), reponse_groq(json.dumps({"nom": "ok"}))]

    resultat = generer_structure(client, "modele", [], Petit, agent="test", execution_id="t")

    assert resultat.nom == "ok"
    assert client.chat.completions.create.call_count == 2


def test_autre_400_remonte_immediatement():
    client = Mock()
    client.chat.completions.create.side_effect = erreur_400("invalid_request")

    with pytest.raises(groq.BadRequestError):
        generer_structure(client, "modele", [], Petit, agent="test", execution_id="t")

    assert client.chat.completions.create.call_count == 1