from datetime import date
from unittest.mock import Mock

import pytest
from test_slack import fausse_synthese
from test_superviseur import analyse_d_hier, signaux

from veille.agents.rapport import Constat
from veille.livrables.validation import (
    creer_envoi,
    decider,
    enregistrer_envoi,
    evaluer_confiance,
    lister_en_attente,
)

AUJOURD_HUI = date(2026, 10, 23)


def synthese_sans_echec():
    return fausse_synthese().model_copy(update={"echecs": {}})


def analyse_saine(**modifs):
    analyse = analyse_d_hier(signaux()).model_copy(update={"date": AUJOURD_HUI})
    rapport = analyse.rapport.model_copy(update={"offres": [Constat(affirmation="Coffret offert.", sources=["meta"])]})
    return analyse.model_copy(update={"rapport": rapport, **modifs})


# --- Évaluer la confiance (par le code, sur des faits vérifiables) ---

def test_confiance_haute_quand_tout_va_bien():
    confiance = evaluer_confiance(synthese_sans_echec(), [analyse_saine()], AUJOURD_HUI)
    assert confiance.haute and confiance.raisons == []


def test_marque_en_echec_confiance_basse():
    confiance = evaluer_confiance(fausse_synthese(), [analyse_saine()], AUJOURD_HUI)   # Horace en échec
    assert not confiance.haute and confiance.raisons == ["Horace : analyse en échec"]


@pytest.mark.parametrize(("modifs", "attendu"), [
    ({"signaux": signaux(erreurs=("meta",))}, "source(s) en erreur (meta)"),
    ({"nb_collectes": 2}, "collecte relancée"),
    ({"date": date(2026, 10, 20)}, "analyse périmée"),
])
def test_chaque_signal_d_alerte_baisse_la_confiance(modifs, attendu):
    confiance = evaluer_confiance(synthese_sans_echec(), [analyse_saine(**modifs)], AUJOURD_HUI)
    assert not confiance.haute and attendu in confiance.raisons[0]


def test_rapport_vide_malgre_des_pubs():
    analyse = analyse_saine()
    analyse = analyse.model_copy(update={"rapport": analyse.rapport.model_copy(update={"offres": []})})
    confiance = evaluer_confiance(synthese_sans_echec(), [analyse], AUJOURD_HUI)
    assert confiance.raisons == ["Typology : rapport vide malgré 1 pub(s)"]


# --- File d'attente et décision humaine ---

def envoi_en_attente(dossier):
    envoi = creer_envoi({"text": "Veille", "blocks": []}, None, ["Horace : analyse en échec"])
    enregistrer_envoi(envoi, dossier)
    return envoi


def test_approuver_envoie_une_seule_fois(tmp_path):
    envoi, envoyer = envoi_en_attente(tmp_path), Mock()

    resultat = decider(envoi.id, approuver=True, par="maeva", envoyer=envoyer, dossier=tmp_path)

    assert resultat.statut == "approuve" and resultat.decide_par == "maeva"
    assert "Relu et validé par maeva" in str(envoyer.call_args.args[0])
    with pytest.raises(ValueError, match="déjà approuve"):
        decider(envoi.id, approuver=True, par="maeva", envoyer=envoyer, dossier=tmp_path)
    envoyer.assert_called_once()                                    # idempotence : jamais deux fois
    assert lister_en_attente(tmp_path) == []


def test_rejeter_n_envoie_rien_et_garde_le_motif(tmp_path):
    envoi, envoyer = envoi_en_attente(tmp_path), Mock()

    resultat = decider(envoi.id, approuver=False, par="maeva", envoyer=envoyer, motif="TikTok en panne", dossier=tmp_path)

    envoyer.assert_not_called()
    assert resultat.statut == "rejete" and resultat.motif == "TikTok en panne"


def test_echec_d_envoi_laisse_l_envoi_en_attente(tmp_path):
    envoi = envoi_en_attente(tmp_path)

    with pytest.raises(RuntimeError):
        decider(envoi.id, approuver=True, par="maeva", envoyer=Mock(side_effect=RuntimeError("Slack down")), dossier=tmp_path)

    assert [e.id for e in lister_en_attente(tmp_path)] == [envoi.id]   # on pourra réessayer


def test_identifiant_inconnu(tmp_path):
    with pytest.raises(ValueError, match="Aucun envoi"):
        decider("inconnu", approuver=True, par="maeva", envoyer=Mock(), dossier=tmp_path)
