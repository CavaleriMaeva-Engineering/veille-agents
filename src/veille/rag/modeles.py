"""Modèles locaux et gratuits (sentence-transformers), téléchargés une fois depuis Hugging Face.

Imports tardifs : sentence-transformers charge PyTorch (plusieurs secondes), inutile pour les tests,
qui utilisent un faux encodeur.
"""

from veille.rag.index import Encodeur
from veille.rag.recherche import Reranker

# Bi-encoder multilingue : 384 dimensions, ~120 Mo, entraîné à rapprocher des phrases de même sens.
MODELE_EMBEDDING = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Cross-encoder multilingue entraîné sur mMARCO (questions / passages) : note la pertinence d'une paire.
MODELE_RERANKER = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def charger_encodeur(nom: str = MODELE_EMBEDDING) -> Encodeur:
    from sentence_transformers import SentenceTransformer

    modele = SentenceTransformer(nom)
    return lambda textes: modele.encode(textes, convert_to_numpy=True)


def charger_reranker(nom: str = MODELE_RERANKER) -> Reranker:
    from sentence_transformers import CrossEncoder

    modele = CrossEncoder(nom)
    return lambda question, textes: [float(s) for s in modele.predict([(question, t) for t in textes])]
