"""API HTTP : lancer une veille, suivre sa progression en temps réel (SSE), consulter résultat et coût.

Lancement local :  uv run uvicorn veille.api.app:app_depuis_env --factory --reload
Toutes les routes sauf /sante exigent l'en-tête X-API-Key (clé VEILLE_API_KEY). Sans clé configurée, l'API reste
fermée (503) : un serveur qui déclenche des scrapings payants ne doit jamais s'ouvrir par oubli de configuration.
"""

import importlib.util
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from apify_client import ApifyClient
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

from veille.agents.memoire import construire_rappel
from veille.agents.superviseur import lancer_veille
from veille.api.executions import (
    FORMAT_ID,
    PING,
    DejaEnCours,
    Options,
    Registre,
    formater_sse,
)
from veille.couts import Bilan, faire_bilan
from veille.llm.client import creer_client_groq
from veille.settings import Config, Secrets, charger_config
from veille.traces import lire_spans


def memoire_disponible() -> bool:
    """La mémoire long terme a besoin de sentence-transformers (groupe « rag », absent de l'image Docker légère)."""
    return importlib.util.find_spec("sentence_transformers") is not None


def lancer_en_reel(config: Config, memoire: bool, execution_id: str):
    """Le vrai lancement : clients Groq et Apify, mémoire optionnelle. Importé tard pour garder le démarrage rapide."""
    secrets_ = Secrets()
    rappeler = None
    if memoire:
        from veille.rag.modeles import charger_encodeur

        rappeler = construire_rappel([Path("sorties"), Path("sorties/archives")], charger_encodeur())
    return lancer_veille(
        config, creer_client_groq(secrets_), ApifyClient(secrets_.apify_token.get_secret_value()),
        execution_id, rappeler=rappeler,
    )


def creer_app(
    *,
    cle_api: str | None,
    lancer: Callable[[Config, bool, str], object] = lancer_en_reel,
    charger: Callable[[], Config] = charger_config,
    dossier_traces: Path = Path("traces"),
    memoire_ok: Callable[[], bool] = memoire_disponible,
) -> FastAPI:
    """Tout ce qui touche au monde extérieur (lancement, config, disque) est injectable : les tests passent
    un faux lanceur et un dossier temporaire, sans Groq ni Apify."""
    app = FastAPI(title="veille-agents", version="0.1.0")
    registre = Registre(lancer, dossier_traces)

    def verifier_cle(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if not cle_api:
            raise HTTPException(503, "API non configurée : définir VEILLE_API_KEY.")
        # compare_digest : durée constante, pour ne pas révéler la clé caractère par caractère par le temps de réponse.
        if x_api_key is None or not secrets.compare_digest(x_api_key.encode(), cle_api.encode()):
            raise HTTPException(401, "Clé d'API absente ou invalide (en-tête X-API-Key).")

    protege = [Depends(verifier_cle)]

    @app.get("/sante")
    def sante() -> dict:
        return {"statut": "ok", "veille_en_cours": registre.en_cours}

    @app.post("/veilles", status_code=202, dependencies=protege)
    def lancer_une_veille(options: Options | None = None) -> dict:
        options = options or Options()
        config = charger()
        if options.marques:
            inconnues = sorted(set(options.marques) - {m.nom for m in config.marques})
            if inconnues:
                raise HTTPException(422, f"Marque(s) absente(s) de la config : {', '.join(inconnues)}.")
            config = config.model_copy(update={"marques": [m for m in config.marques if m.nom in options.marques]})
        if options.memoire and not memoire_ok():
            raise HTTPException(422, "Mémoire long terme indisponible : le groupe de dépendances « rag » n'est pas installé.")
        try:
            execution = registre.demarrer(config, options)
        except DejaEnCours as erreur:
            raise HTTPException(409, str(erreur), headers={"Retry-After": "30"}) from erreur
        return execution.vue()

    @app.get("/veilles", dependencies=protege)
    def lister_les_veilles() -> list[dict]:
        return [execution.vue() for execution in registre.recentes()]

    @app.get("/veilles/{execution_id}", dependencies=protege)
    def lire_une_veille(execution_id: str) -> dict:
        execution = registre.trouver(execution_id)
        if execution is None:
            raise HTTPException(404, "Veille inconnue (le registre est en mémoire : il est vidé au redémarrage).")
        return execution.vue()

    @app.get("/veilles/{execution_id}/evenements", dependencies=protege)
    def suivre_une_veille(
        execution_id: str, last_event_id: Annotated[str | None, Header()] = None
    ) -> StreamingResponse:
        execution = registre.trouver(execution_id)
        if execution is None:
            raise HTTPException(404, "Veille inconnue.")
        # Reprise après coupure : le navigateur (ou le client) renvoie l'id du dernier événement reçu.
        apres = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

        def flux():
            yield "retry: 3000\n\n"   # délai de reconnexion conseillé au client, en millisecondes
            for evenement in execution.suivre(apres):
                yield PING if evenement is None else formater_sse(evenement)

        return StreamingResponse(
            flux(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},   # pas de tampon dans nginx
        )

    @app.get("/veilles/{execution_id}/cout", dependencies=protege)
    def cout_d_une_veille(execution_id: str) -> Bilan:
        # La trace est sur disque : le coût reste consultable après un redémarrage, contrairement au registre.
        chemin = dossier_traces / f"{execution_id}.jsonl"
        if not FORMAT_ID.match(execution_id) or not chemin.exists():
            raise HTTPException(404, "Aucune trace pour cette veille.")
        return faire_bilan(lire_spans(chemin))

    return app


def app_depuis_env() -> FastAPI:
    """Fabrique pour uvicorn (--factory) : la clé vient de l'environnement ou du fichier .env."""
    cle = Secrets().veille_api_key
    return creer_app(cle_api=cle.get_secret_value() if cle else None)
