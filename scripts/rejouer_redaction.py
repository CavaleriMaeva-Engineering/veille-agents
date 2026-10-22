import logging
import sys
import uuid
from pathlib import Path

from veille.agents.rapport import rediger_rapport
from veille.llm.client import creer_client_groq
from veille.settings import Secrets, charger_config
from veille.storage.analyses import charger_analyse

logging.basicConfig(level=logging.INFO, format="%(message)s")

analyse = charger_analyse(Path(sys.argv[1]))
rapport = rediger_rapport(
    creer_client_groq(Secrets()), charger_config().modele, analyse.marque,
    analyse.observations, analyse.signaux, execution_id=f"rejeu-{uuid.uuid4().hex[:8]}",
)
print(rapport.model_dump_json(indent=2))