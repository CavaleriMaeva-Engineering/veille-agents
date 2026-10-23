import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from veille.agents.analyste import AnalyseMarque
from veille.agents.rapport import RapportVeille
from veille.agents.signaux import PubDurable, Signaux
from veille.agents.synthese import (
    SyntheseMarche,
    calculer_signaux_marche,
    rediger_synthese,
)


def analyse(marque: str, nb_meta: int, duree: int | None) -> AnalyseMarque:
    durable = PubDurable(source="meta", texte="x", duree_jours=duree, lien=None) if duree else None
    return AnalyseMarque(
        marque=marque, date=date(2026, 10, 23), execution_id="t", observations=["données brutes"],
        signaux=Signaux(nb_pubs={"meta": nb_meta}, formats={"VIDEO": nb_meta}, pub_la_plus_durable=durable,
                        sources_en_erreur=[]),
        rapport=RapportVeille(marque=marque, produits_pousses=[], messages_et_promesses=[], offres=[],
                              formats_et_plateformes=[], cible=[], donnees_manquantes=[]),
    )


ANALYSES = [analyse("Typology", 5, 282), analyse("Horace", 3, 400), analyse("Respire", 0, None)]
SYNTHESE_VALIDE = {"tendances_communes": [], "positionnements": [], "differences_notables": [], "limites": []}


def test_signaux_marche():
    signaux = calculer_signaux_marche(ANALYSES)

    assert signaux.nb_pubs_par_marque == {"Typology": 5, "Horace": 3, "Respire": 0}
    assert signaux.formats == {"VIDEO": 8}
    assert [d.marque for d in signaux.classement_pubs_durables] == ["Horace", "Typology"]   # Respire n'en a pas
    assert signaux.marques_sans_pub == ["Respire"]

def test_synthese_compacte_et_echecs_transmis():
    message = SimpleNamespace(content=json.dumps(SYNTHESE_VALIDE), tool_calls=None)
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    )

    synthese = rediger_synthese(client, "modele", ANALYSES, {"The Ordinary": "panne"},
                                calculer_signaux_marche(ANALYSES), "t-1")

    assert isinstance(synthese, SyntheseMarche)
    contenu = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "The Ordinary" in contenu          # l'échec est signalé au LLM
    assert "données brutes" not in contenu    # les observations ne sont PAS transmises