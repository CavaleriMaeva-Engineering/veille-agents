from types import SimpleNamespace
from unittest.mock import Mock

from veille.llm.client import appeler_llm


def fausse_reponse_groq(contenu=None, tool_calls=None):
    message = SimpleNamespace(content=contenu, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def faux_tool_call(id_, nom, arguments):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=nom, arguments=arguments))


def test_reponse_texte_sans_outil():
    client = Mock()
    client.chat.completions.create.return_value = fausse_reponse_groq(contenu="Bonjour")

    reponse = appeler_llm(client, "modele", [], agent="test", execution_id="t-1")

    assert reponse.texte == "Bonjour"
    assert reponse.appels_outils == []


def test_demande_d_appel_d_outil():
    appel = faux_tool_call("call_1", "chercher_pubs_meta", '{"marque": "Typology"}')
    client = Mock()
    client.chat.completions.create.return_value = fausse_reponse_groq(tool_calls=[appel])

    reponse = appeler_llm(client, "modele", [], agent="test", execution_id="t-1", outils=[{"type": "function"}])

    assert reponse.texte is None
    assert reponse.appels_outils[0].nom == "chercher_pubs_meta"
    assert reponse.appels_outils[0].id == "call_1"


def test_outils_transmis_seulement_s_il_y_en_a():
    client = Mock()
    client.chat.completions.create.return_value = fausse_reponse_groq(contenu="ok")

    appeler_llm(client, "modele", [], agent="test", execution_id="t-1")

    assert "tools" not in client.chat.completions.create.call_args.kwargs