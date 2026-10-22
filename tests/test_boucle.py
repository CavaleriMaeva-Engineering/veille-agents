import json
from types import SimpleNamespace
from unittest.mock import Mock

from veille.agents.boucle import executer_agent
from veille.tools.meta import OUTIL_CHERCHER_PUBS_META, ArgsChercherPubsMeta
from veille.tools.registre import Outil


def reponse_groq(contenu=None, appels=()):
    tool_calls = [
        SimpleNamespace(id=id_, function=SimpleNamespace(name=nom, arguments=arguments))
        for id_, nom, arguments in appels
    ] or None
    message = SimpleNamespace(content=contenu, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def faux_llm(*reponses) -> Mock:
    client = Mock()
    client.chat.completions.create.side_effect = list(reponses)
    return client


def lancer(client: Mock, fonction: Mock, max_tours: int = 6):
    outils = {"chercher_pubs_meta": Outil(OUTIL_CHERCHER_PUBS_META, ArgsChercherPubsMeta, fonction)}
    return executer_agent(
        client, "modele", "Tu es un analyste.", "Que fait Typology ?",
        outils, agent="test", execution_id="t-1", max_tours=max_tours,
    )


META_TYPOLOGY = '{"marque": "Typology"}'


def test_reponse_directe_sans_outil():
    client = faux_llm(reponse_groq("Je n'ai besoin d'aucun outil."))
    fonction = Mock()

    resultat = lancer(client, fonction)

    assert resultat.arret == "reponse_finale"
    assert resultat.tours == 1
    assert resultat.tokens == 15
    fonction.assert_not_called()


def test_un_outil_puis_reponse():
    client = faux_llm(
        reponse_groq(appels=[("c1", "chercher_pubs_meta", META_TYPOLOGY)]),
        reponse_groq("Typology pousse son calendrier de l'Avent."),
    )
    fonction = Mock(return_value={"nb_pubs": 5})

    resultat = lancer(client, fonction)

    assert resultat.reponse == "Typology pousse son calendrier de l'Avent."
    assert resultat.tours == 2
    fonction.assert_called_once_with(marque="Typology", max_pubs=10)
    roles = [m["role"] for m in resultat.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    observation = resultat.messages[3]
    assert observation["tool_call_id"] == "c1"
    assert json.loads(observation["content"]) == {"nb_pubs": 5}


def test_doublon_non_reexecute():
    client = faux_llm(
        reponse_groq(appels=[("c1", "chercher_pubs_meta", '{"marque": "Typology", "max_pubs": 5}')]),
        reponse_groq(appels=[("c2", "chercher_pubs_meta", '{"max_pubs":5,"marque":"Typology"}')]),
        reponse_groq("Fini."),
    )
    fonction = Mock(return_value={"nb_pubs": 5})

    resultat = lancer(client, fonction)

    assert fonction.call_count == 1
    assert "déjà effectué" in resultat.messages[5]["content"]
    assert resultat.messages[5]["tool_call_id"] == "c2"


def test_limite_de_tours_force_une_reponse():
    client = faux_llm(
        reponse_groq(appels=[("c1", "chercher_pubs_meta", '{"marque": "Typology"}')]),
        reponse_groq(appels=[("c2", "chercher_pubs_meta", '{"marque": "Respire"}')]),
        reponse_groq("Rapport partiel : TikTok non consulté."),
    )
    fonction = Mock(return_value={"nb_pubs": 1})

    resultat = lancer(client, fonction, max_tours=2)

    assert resultat.arret == "limite_tours"
    assert resultat.reponse == "Rapport partiel : TikTok non consulté."
    assert client.chat.completions.create.call_count == 3
    assert client.chat.completions.create.call_args.kwargs["tool_choice"] == "none"


def test_bug_d_outil_ne_tue_pas_l_agent():
    client = faux_llm(
        reponse_groq(appels=[("c1", "chercher_pubs_meta", META_TYPOLOGY)]),
        reponse_groq("Meta indisponible, je n'ai pas pu conclure."),
    )
    fonction = Mock(side_effect=RuntimeError("bug"))

    resultat = lancer(client, fonction)

    assert "erreur interne" in resultat.messages[3]["content"]
    assert resultat.arret == "reponse_finale"


def test_arguments_invalides_renvoyes_au_llm():
    client = faux_llm(
        reponse_groq(appels=[("c1", "chercher_pubs_meta", '{"marque": "Typology", "max_pubs": 500}')]),
        reponse_groq(appels=[("c2", "chercher_pubs_meta", '{"marque": "Typology", "max_pubs": 20}')]),
        reponse_groq("Fini."),
    )
    fonction = Mock(return_value={"nb_pubs": 20})

    resultat = lancer(client, fonction)

    assert "max_pubs" in resultat.messages[3]["content"]
    fonction.assert_called_once_with(marque="Typology", max_pubs=20)