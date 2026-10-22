import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from veille.agents.rapport import RapportVeille, extraire_observations, rediger_rapport

RAPPORT_VALIDE = {
    "marque": "Typology",
    "produits_pousses": [{"affirmation": "Calendrier de l'Avent 2026, édition limitée.", "source": "meta"}],
    "messages_et_promesses": [],
    "offres": [{"affirmation": "184,90 € pour 402,40 € de produits.", "source": "site"}],
    "formats_et_plateformes": [],
    "cible": [],
    "pub_la_plus_durable": None,
    "donnees_manquantes": ["TikTok indisponible."],
}


def reponse_groq(contenu: str):
    message = SimpleNamespace(content=contenu, tool_calls=None)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def faux_llm(*contenus: str) -> Mock:
    client = Mock()
    client.chat.completions.create.side_effect = [reponse_groq(c) for c in contenus]
    return client


def rediger(client: Mock) -> RapportVeille:
    return rediger_rapport(client, "modele", "Typology", ['{"nb_pubs": 5}'], execution_id="t-1")


def test_rapport_valide():
    client = faux_llm(json.dumps(RAPPORT_VALIDE))

    rapport = rediger(client)

    assert rapport.marque == "Typology"
    assert rapport.offres[0].source == "site"
    assert rapport.pub_la_plus_durable is None


def test_schema_strict_envoye():
    client = faux_llm(json.dumps(RAPPORT_VALIDE))

    rediger(client)

    format_envoye = client.chat.completions.create.call_args.kwargs["response_format"]
    schema = format_envoye["json_schema"]["schema"]
    assert format_envoye["json_schema"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert "pub_la_plus_durable" in schema["required"]   # requis, même s'il peut valoir null
    assert "tools" not in client.chat.completions.create.call_args.kwargs


def test_json_invalide_puis_corrige():
    client = faux_llm('{"marque": "Typology"}', json.dumps(RAPPORT_VALIDE))

    rapport = rediger(client)

    assert rapport.marque == "Typology"
    assert client.chat.completions.create.call_count == 2
    dernier_message = client.chat.completions.create.call_args.kwargs["messages"][-1]
    assert "ne respecte pas le format" in dernier_message["content"]


def test_abandonne_apres_max_essais():
    client = faux_llm("pas du JSON", "toujours pas")

    with pytest.raises(ValidationError):
        rediger(client)

    assert client.chat.completions.create.call_count == 2


def test_source_inconnue_refusee():
    rapport = dict(RAPPORT_VALIDE, offres=[{"affirmation": "x", "source": "linkedin"}])

    with pytest.raises(ValidationError):
        RapportVeille.model_validate(rapport)


def test_extraire_observations():
    messages = [
        {"role": "system", "content": "..."},
        {"role": "assistant", "content": "", "tool_calls": []},
        {"role": "tool", "tool_call_id": "c1", "content": '{"nb_pubs": 5}'},
        {"role": "assistant", "content": "Collecte terminée."},
    ]

    assert extraire_observations(messages) == ['{"nb_pubs": 5}']


def test_budget_de_sortie_et_effort_envoyes():
    client = faux_llm(json.dumps(RAPPORT_VALIDE))

    rediger(client)

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_completion_tokens"] >= 2048
    assert kwargs["reasoning_effort"] == "low"


def test_null_en_texte_devient_none():
    rapport = RapportVeille.model_validate(dict(RAPPORT_VALIDE, pub_la_plus_durable="null"))

    assert rapport.pub_la_plus_durable is None