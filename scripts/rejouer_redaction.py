import json
import logging
import sys
import uuid
from pathlib import Path

from veille.agents.rapport import rediger_rapport
from veille.agents.signaux import Signaux
from veille.llm.client import creer_client_groq
from veille.settings import Secrets, charger_config

logging.basicConfig(level=logging.INFO, format="%(message)s")

# On ne relit que les données de la collecte : le rapport enregistré peut avoir un ancien format.
donnees = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
signaux = Signaux.model_validate(donnees["signaux"])

rapport = rediger_rapport(
    creer_client_groq(Secrets()), charger_config().modele, donnees["marque"],
    donnees["observations"], signaux, execution_id=f"rejeu-{uuid.uuid4().hex[:8]}",
)
print(rapport.model_dump_json(indent=2))