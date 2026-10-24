import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")   # la couche HTTP a besoin de FastAPI ; la logique est testée dans test_executions.py

from fastapi.testclient import TestClient

from veille.api.app import creer_app
from veille.settings import Config, Marque
from veille.traces import span

CLE = "cle-de-test"
ENTETES = {"X-API-Key": CLE}
CONFIG = Config(
    marche="t", modele="m",
    marques=[Marque(nom="Typology", site="https://typology.com"), Marque(nom="Horace", site="https://horace.com")],
)


def lanceur_rapide(config, memoire, execution_id):
    with span("llm", "openai/gpt-oss-20b", agent="collecteur", modele="openai/gpt-oss-20b", tentative=1) as a:
        a.update(tokens_entree=1000, tokens_caches=0, tokens_sortie=100)
    return SimpleNamespace(analyses=[], echecs={})


def client(tmp_path, lancer=lanceur_rapide, cle_api=CLE, memoire_ok=lambda: True):
    app = creer_app(
        cle_api=cle_api, lancer=lancer, charger=lambda: CONFIG, dossier_traces=tmp_path, memoire_ok=memoire_ok,
    )
    return TestClient(app)


def lancer_et_attendre(c) -> str:
    execution_id = c.post("/veilles", headers=ENTETES).json()["id"]
    for _ in range(100):
        if c.get(f"/veilles/{execution_id}", headers=ENTETES).json()["statut"] != "en_cours":
            return execution_id
        threading.Event().wait(0.05)
    raise AssertionError("la veille ne se termine pas")


# --- Accès ---------------------------------------------------------------------------------------------

def test_la_sante_est_ouverte(tmp_path):
    assert client(tmp_path).get("/sante").json()["statut"] == "ok"


def test_sans_cle_ou_avec_une_mauvaise_cle_401(tmp_path):
    c = client(tmp_path)
    assert c.get("/veilles").status_code == 401
    assert c.get("/veilles", headers={"X-API-Key": "autre"}).status_code == 401
    assert c.post("/veilles").status_code == 401


def test_api_fermee_si_aucune_cle_n_est_configuree(tmp_path):
    c = client(tmp_path, cle_api=None)
    assert c.get("/veilles", headers=ENTETES).status_code == 503   # même avec un en-tête : fermée par défaut


# --- Lancer et suivre ----------------------------------------------------------------------------------

def test_lancer_une_veille_renvoie_202_et_un_id(tmp_path):
    reponse = client(tmp_path).post("/veilles", headers=ENTETES)

    assert reponse.status_code == 202
    assert reponse.json()["id"].startswith("veille-")
    assert reponse.json()["statut"] in {"en_cours", "terminee"}


def test_pendant_un_run_un_second_post_renvoie_409(tmp_path):
    libere = threading.Event()

    def lanceur(config, memoire, execution_id):
        libere.wait(timeout=5)
        return SimpleNamespace(analyses=[], echecs={})

    c = client(tmp_path, lancer=lanceur)
    premiere = c.post("/veilles", headers=ENTETES).json()["id"]

    second = c.post("/veilles", headers=ENTETES)
    assert second.status_code == 409
    assert premiere in second.json()["detail"]
    assert second.headers["Retry-After"] == "30"

    libere.set()


def test_marque_inconnue_422(tmp_path):
    reponse = client(tmp_path).post("/veilles", json={"marques": ["Inconnue"]}, headers=ENTETES)
    assert reponse.status_code == 422
    assert "Inconnue" in reponse.json()["detail"]


def test_memoire_demandee_mais_indisponible_422(tmp_path):
    reponse = client(tmp_path, memoire_ok=lambda: False).post("/veilles", json={"memoire": True}, headers=ENTETES)
    assert reponse.status_code == 422


def test_le_flux_sse_contient_les_spans_et_la_fin(tmp_path):
    c = client(tmp_path)
    execution_id = lancer_et_attendre(c)

    reponse = c.get(f"/veilles/{execution_id}/evenements", headers=ENTETES)

    assert reponse.headers["content-type"].startswith("text/event-stream")
    assert "id: 1\nevent: span\n" in reponse.text
    assert "event: fin\n" in reponse.text
    assert '"tokens_entree": 1000' in reponse.text


def test_reprise_avec_last_event_id(tmp_path):
    c = client(tmp_path)
    execution_id = lancer_et_attendre(c)

    reponse = c.get(f"/veilles/{execution_id}/evenements", headers={**ENTETES, "Last-Event-ID": "1"})

    assert "id: 1\n" not in reponse.text
    assert "id: 2\nevent: fin\n" in reponse.text


def test_veille_inconnue_404(tmp_path):
    c = client(tmp_path)
    assert c.get("/veilles/veille-00000000", headers=ENTETES).status_code == 404
    assert c.get("/veilles/veille-00000000/evenements", headers=ENTETES).status_code == 404


# --- Coût --------------------------------------------------------------------------------------------

def test_le_cout_vient_de_la_trace(tmp_path):
    c = client(tmp_path)
    execution_id = lancer_et_attendre(c)

    bilan = c.get(f"/veilles/{execution_id}/cout", headers=ENTETES).json()

    assert bilan["total"]["appels"] == 1
    assert bilan["total"]["tokens_entree"] == 1000


def test_le_cout_refuse_un_id_qui_n_est_pas_une_veille(tmp_path):
    (tmp_path.parent / "secret.jsonl").write_text("{}")
    c = client(tmp_path)
    assert c.get("/veilles/..%2Fsecret/cout", headers=ENTETES).status_code == 404
    assert c.get("/veilles/veille-ffffffff/cout", headers=ENTETES).status_code == 404
