"""Tracing : un span par appel LLM, par appel d'outil et par étape, écrit en JSONL (une ligne par span).

Un span = une opération chronométrée : type (execution, etape, llm, outil), nom, début, durée, statut, attributs
(tokens, coût, taille du résultat...) et le span parent. Les parents forment un arbre :
execution > marque > collecte > llm / outil, ce qui permet de répondre à « où sont passés le temps et l'argent ? ».

Le span courant vit dans une ContextVar : il suit le code dans les threads lancés par asyncio.to_thread
(appels d'outils en parallèle), qui copient le contexte. Sans trace active (tests, scripts d'essai),
span() ne fait que chronométrer : rien n'est écrit.
"""

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class Trace:
    """Un fichier JSONL par exécution. Le verrou protège l'écriture : des outils finissent en parallèle.

    `sur_span` : fonction appelée avec chaque span fermé (l'API s'en sert pour diffuser la progression).
    """

    def __init__(self, execution_id: str, chemin: Path, sur_span: Callable[[dict], None] | None = None):
        self.execution_id = execution_id
        self.chemin = chemin
        self._sur_span = sur_span
        self._verrou = threading.Lock()

    def ecrire(self, span: dict) -> None:
        ligne = json.dumps(span, ensure_ascii=False, default=str)
        with self._verrou, open(self.chemin, "a", encoding="utf-8") as f:
            f.write(ligne + "\n")
        if self._sur_span is not None:
            try:
                self._sur_span(span)
            except Exception:
                logger.exception("sur_span a échoué")


_trace: ContextVar[Trace | None] = ContextVar("trace", default=None)
_span_courant: ContextVar[dict | None] = ContextVar("span_courant", default=None)


@contextmanager
def tracer(
    execution_id: str, dossier: Path = Path("traces"), sur_span: Callable[[dict], None] | None = None
) -> Iterator[Trace]:
    """Active la trace d'une exécution : tous les spans ouverts dedans sont écrits dans dossier/<id>.jsonl."""
    dossier.mkdir(parents=True, exist_ok=True)
    trace = Trace(execution_id, dossier / f"{execution_id}.jsonl", sur_span)
    jeton = _trace.set(trace)
    try:
        with span("execution", execution_id):
            yield trace
    finally:
        _trace.reset(jeton)


@contextmanager
def span(type_: str, nom: str, **attributs) -> Iterator[dict]:
    """Chronomètre un bloc. Renvoie le dictionnaire des attributs, que le bloc peut compléter (tokens, coût...)."""
    trace = _trace.get()
    parent = _span_courant.get()
    donnees = {
        "trace_id": trace.execution_id if trace else None,
        "span_id": uuid.uuid4().hex[:12],
        "parent_id": parent["span_id"] if parent else None,
        "type": type_,
        "nom": nom,
        "debut": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "attributs": dict(attributs),
    }
    jeton = _span_courant.set(donnees)
    debut = time.perf_counter()
    try:
        yield donnees["attributs"]
        donnees["statut"] = "ok"
    except BaseException as erreur:
        donnees["statut"] = "erreur"
        donnees["erreur"] = repr(erreur)[:300]
        raise   # le span constate l'erreur, il ne la traite pas
    finally:
        _span_courant.reset(jeton)
        donnees["duree_ms"] = round((time.perf_counter() - debut) * 1000, 1)
        if trace is not None:
            trace.ecrire(donnees)


def noter(**attributs) -> None:
    """Ajoute des attributs au span courant, depuis un code qui ne l'a pas ouvert (ex. le coût Apify dans un outil)."""
    courant = _span_courant.get()
    if courant is not None:
        courant["attributs"].update(attributs)


def lire_spans(chemin: Path) -> list[dict]:
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f if ligne.strip()]
