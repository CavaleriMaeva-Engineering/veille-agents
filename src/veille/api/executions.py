"""Exécutions lancées par l'API : registre en mémoire, journal d'événements rejouable, un seul run à la fois.

Ce module n'importe pas FastAPI : la logique (qui tourne, quels événements, dans quel ordre) se teste sans
serveur. app.py n'est qu'une fine couche HTTP par-dessus.
"""

import json
import logging
import re
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from veille.settings import Config
from veille.traces import tracer

logger = logging.getLogger(__name__)

MAX_EXECUTIONS_EN_MEMOIRE = 50
FORMAT_ID = re.compile(r"^veille-[0-9a-f]{8}$")   # aussi une protection : l'id sert à fabriquer un nom de fichier
PING = ": ping\n\n"                                 # commentaire SSE : garde la connexion ouverte à travers les proxys
DELAI_PING = 15.0


class Options(BaseModel):
    memoire: bool = False                # mémoire long terme (RAG) : charge des modèles locaux, lent au premier appel
    marques: list[str] | None = None     # sous-ensemble des marques de la config ; None = toutes


class DejaEnCours(Exception):
    def __init__(self, execution_id: str):
        super().__init__(f"Une veille est déjà en cours : {execution_id}")
        self.execution_id = execution_id


def nom_d_erreur(texte: str) -> str:
    """« RateLimitError("Error code: 429 ... org_xyz ... ») » -> « RateLimitError ».

    Un message d'erreur brut peut contenir des identifiants de compte ou des morceaux de requête : il reste dans
    les logs serveur, il ne sort jamais par l'API."""
    return texte.split("(")[0].strip() or "Erreur"


def evenement_depuis_span(span: dict) -> dict | None:
    """Ce qu'un client a le droit de voir d'un span : une liste blanche d'attributs, jamais le span entier.

    Les arguments d'outils, les messages d'erreur bruts et les prompts n'en font pas partie."""
    attributs = span["attributs"]
    commun = {"nom": span["nom"], "statut": span["statut"], "duree_ms": span["duree_ms"]}
    if span["type"] == "etape":
        return {"type": "etape", **commun, "marque": attributs.get("marque"), "numero": attributs.get("numero")}
    if span["type"] == "llm":
        donnees = {
            "type": "llm", **commun,
            "agent": attributs.get("agent"), "tentative": attributs.get("tentative"),
            "tokens_entree": attributs.get("tokens_entree"), "tokens_caches": attributs.get("tokens_caches"),
            "tokens_sortie": attributs.get("tokens_sortie"), "cout_usd": attributs.get("cout_usd"),
        }
        if span["statut"] != "ok":
            donnees["erreur"] = nom_d_erreur(span.get("erreur", ""))
        return donnees
    if span["type"] == "outil":
        return {"type": "outil", **commun, "resultat": attributs.get("resultat"), "caracteres": attributs.get("caracteres")}
    return None   # le span racine « execution » : sa fin est annoncée par l'événement « fin »


def formater_sse(evenement: dict) -> str:
    """Format Server-Sent Events : des lignes « champ: valeur », un événement fini par une ligne vide."""
    donnees = json.dumps(evenement["donnees"], ensure_ascii=False)   # sans retour à la ligne : une seule ligne data
    return f"id: {evenement['id']}\nevent: {evenement['type']}\ndata: {donnees}\n\n"


def resumer(resultat) -> dict:
    return {
        "marques": [
            {
                "marque": a.marque, "decision": a.decision, "nb_collectes": a.nb_collectes,
                "nb_pubs": sum(a.signaux.nb_pubs.values()),
                "score_changement": a.changements.score if a.changements and a.changements.comparable else None,
                "nb_alertes": len(a.alertes),
            }
            for a in resultat.analyses
        ],
        "echecs": {marque: nom_d_erreur(erreur) for marque, erreur in resultat.echecs.items()},
    }


class Execution:
    def __init__(self, execution_id: str, options: Options):
        self.id = execution_id
        self.options = options
        self.cree_le = datetime.now(UTC)
        self.fini_le: datetime | None = None
        self.statut = "en_cours"          # en_cours -> terminee | echec
        self.resume: dict | None = None
        self.erreur: str | None = None
        self._evenements: list[dict] = []
        self._cond = threading.Condition()

    @property
    def fini(self) -> bool:
        return self.statut != "en_cours"

    def ajouter(self, type_: str, donnees: dict) -> None:
        with self._cond:
            self._evenements.append({"id": len(self._evenements) + 1, "type": type_, "donnees": donnees})
            self._cond.notify_all()

    def ajouter_span(self, span: dict) -> None:
        donnees = evenement_depuis_span(span)
        if donnees is not None:
            self.ajouter("span", donnees)

    def terminer(self, statut: str, resume: dict | None = None, erreur: str | None = None) -> None:
        # L'événement « fin » et le changement de statut dans le MÊME verrou : un lecteur ne peut pas voir
        # « fini » sans avoir reçu « fin ».
        with self._cond:
            self.statut, self.resume, self.erreur, self.fini_le = statut, resume, erreur, datetime.now(UTC)
            donnees = {"statut": statut, "resume": resume, "erreur": erreur}
            self._evenements.append({"id": len(self._evenements) + 1, "type": "fin", "donnees": donnees})
            self._cond.notify_all()

    def attendre(self, timeout: float) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: self.fini, timeout)

    def suivre(self, apres: int = 0, delai_ping: float = DELAI_PING) -> Iterator[dict | None]:
        """Les événements d'id > `apres`, puis les nouveaux au fur et à mesure ; None = rien de neuf depuis
        `delai_ping` secondes (le serveur envoie alors un ping). S'arrête quand l'exécution est finie ET que
        tout a été remis. `apres` permet de reprendre après une coupure (en-tête Last-Event-ID)."""
        vus = apres
        while True:
            with self._cond:
                self._cond.wait_for(lambda deja_vus=vus: len(self._evenements) > deja_vus or self.fini, delai_ping)
                nouveaux = self._evenements[vus:]
                fini = self.fini
            if nouveaux:
                yield from nouveaux
                vus += len(nouveaux)
            elif fini:
                return
            else:
                yield None

    def vue(self) -> dict:
        return {
            "id": self.id, "statut": self.statut, "options": self.options.model_dump(),
            "cree_le": self.cree_le.isoformat(), "fini_le": self.fini_le.isoformat() if self.fini_le else None,
            "resume": self.resume, "erreur": self.erreur,
        }


class Registre:
    """Les exécutions récentes, et le verrou qui n'en autorise qu'une à la fois.

    Une seule : chaque veille consomme des crédits Apify et le quota de tokens du fournisseur ; deux veilles
    parallèles se battraient pour le même quota. Un POST pendant un run reçoit 409.
    Le registre est en mémoire : il est perdu au redémarrage. Les traces et les analyses, elles, restent sur disque."""

    def __init__(self, lancer: Callable[[Config, bool, str], object], dossier_traces: Path):
        self._lancer = lancer
        self._dossier_traces = dossier_traces
        self._occupe = threading.Lock()
        self._executions: OrderedDict[str, Execution] = OrderedDict()
        self._en_cours: str | None = None

    def demarrer(self, config: Config, options: Options) -> Execution:
        if not self._occupe.acquire(blocking=False):
            raise DejaEnCours(self._en_cours or "?")
        execution = Execution(f"veille-{uuid.uuid4().hex[:8]}", options)
        self._en_cours = execution.id
        self._executions[execution.id] = execution
        while len(self._executions) > MAX_EXECUTIONS_EN_MEMOIRE:
            self._executions.popitem(last=False)
        threading.Thread(target=self._travailler, args=(execution, config), daemon=True).start()
        return execution

    def _travailler(self, execution: Execution, config: Config) -> None:
        statut, resume, nom_erreur = "terminee", None, None
        try:
            # Le tracer est ouvert DANS le thread : le contexte (ContextVar) est propre à chaque thread.
            with tracer(execution.id, self._dossier_traces, sur_span=execution.ajouter_span):
                resultat = self._lancer(config, execution.options.memoire, execution.id)
            resume = resumer(resultat)
        except Exception as erreur:
            logger.exception("veille %s en échec", execution.id)
            statut, nom_erreur = "echec", nom_d_erreur(repr(erreur))
        finally:
            # Libérer AVANT d'annoncer la fin : un client qui reçoit « fin » peut relancer aussitôt sans 409.
            self._en_cours = None
            self._occupe.release()
        execution.terminer(statut, resume=resume, erreur=nom_erreur)

    @property
    def en_cours(self) -> str | None:
        return self._en_cours

    def trouver(self, execution_id: str) -> Execution | None:
        return self._executions.get(execution_id)

    def recentes(self) -> list[Execution]:
        return list(reversed(self._executions.values()))
