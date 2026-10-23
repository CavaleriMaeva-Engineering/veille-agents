import logging
import uuid
from datetime import date, datetime

from veille.agents.synthese import (
    SyntheseVeille,
    calculer_signaux_marche,
    rediger_synthese,
)
from veille.llm.client import creer_client_groq
from veille.settings import Secrets, charger_config
from veille.storage.analyses import (
    charger_dernieres_analyses,
    enregistrer_synthese,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")

config = charger_config()
analyses, echecs = [], {}
analyses, echecs = charger_dernieres_analyses([m.nom for m in config.marques])

execution_id = f"synthese-{uuid.uuid4().hex[:8]}"
signaux = calculer_signaux_marche(analyses)
synthese = rediger_synthese(creer_client_groq(Secrets()), config.modele, analyses, echecs, signaux, execution_id)

resultat = SyntheseVeille(
    date=date.today(), horodatage=datetime.now(), execution_id=execution_id, marques_analysees=[a.marque for a in analyses],
    echecs=echecs, signaux=signaux, synthese=synthese,
)
print(resultat.model_dump_json(indent=2))
print(f"\nSynthèse enregistrée : {enregistrer_synthese(resultat)}")