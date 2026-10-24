"""Vérifier les évals sans LLM, sans modèle et sans réseau : c'est ce que lance la CI à chaque push.

    uv run python scripts/verifier_evals.py

Code de sortie 0 si tous les contrôles passent, 1 sinon. Voir veille/evals/verification.py pour ce qui est
vérifié, et surtout pour ce qui ne l'est pas.
"""

import sys

from veille.evals.verification import formater, verifier_tout

controles = verifier_tout()
print(formater(controles))
echecs = [c for c in controles if not c.ok]
print(f"\n{len(controles) - len(echecs)} / {len(controles)} contrôles passés")
sys.exit(1 if echecs else 0)
