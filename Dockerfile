# syntax=docker/dockerfile:1
# Image multi-stage : un étage « builder » qui a uv et construit l'environnement, un étage « runtime » qui ne
# garde que Python et l'environnement fini (pas de uv, pas de cache, pas d'outils de build).
ARG PYTHON_VERSION=3.13

# ---- Étage 1 : construire l'environnement virtuel --------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /usr/local/bin/uv

# LINK_MODE=copy : le cache de uv est un montage, on ne peut pas y faire des liens physiques.
# PYTHON_DOWNLOADS=never : on veut le Python de l'image, celui que l'étage runtime aura aussi.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# false (défaut) : image légère, sans PyTorch -> la mémoire long terme (RAG) est indisponible.
# true : ajoute le groupe « rag » (sentence-transformers + PyTorch), l'image pèse plusieurs Go.
ARG AVEC_RAG=false

# 1) Les dépendances seules. Cette couche ne se reconstruit que si pyproject.toml ou uv.lock changent :
#    modifier le code ne relance pas le téléchargement des paquets.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$AVEC_RAG" = "true" ]; then GROUPES="--group rag"; else GROUPES="--no-group rag"; fi; \
    uv sync --frozen --no-dev --no-install-project $GROUPES

# 2) Le projet lui-même, installé dans l'environnement (non éditable : le code est copié dedans).
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$AVEC_RAG" = "true" ]; then GROUPES="--group rag"; else GROUPES="--no-group rag"; fi; \
    uv sync --frozen --no-dev --no-editable $GROUPES

# ---- Étage 2 : l'image qui tourne ------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"

# Pas de root : un utilisateur dédié, sans mot de passe ni shell de connexion.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin veille
WORKDIR /app
COPY --from=builder --chown=veille:veille /app/.venv /app/.venv
COPY --chown=veille:veille config ./config
RUN mkdir sorties traces && chown veille:veille sorties traces
USER veille

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante', timeout=3)"]

# --factory : uvicorn appelle app_depuis_env() au démarrage pour fabriquer l'application.
CMD ["uvicorn", "veille.api.app:app_depuis_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
