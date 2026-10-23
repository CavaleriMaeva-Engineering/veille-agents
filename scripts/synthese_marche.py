import logging
import uuid
from datetime import date

from pydantic import ValidationError

from veille.agents.synthese import (
    SyntheseVeille,
    calculer_signaux_marche,
    rediger_synthese,
)
from veille.llm.client import creer_client_groq
from veille.settings import Secrets, charger_config
from veille.storage.analyses import (
    charger_analyse,
    enregistrer_synthese,
    lister_analyses,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")

config = charger_config()
analyses, echecs = [], {}
for marque in config.marques:
    chemins = lister_analyses(marque.nom)
    if not chemins:
        echecs[marque.nom] = "aucune analyse enregistrée"
        continue
    try:
        analyses.append(charger_analyse(chemins[-1]))   # la plus récente
    except ValidationError:
        echecs[marque.nom] = "analyse enregistrée dans un ancien format"

execution_id = f"synthese-{uuid.uuid4().hex[:8]}"
signaux = calculer_signaux_marche(analyses)
synthese = rediger_synthese(creer_client_groq(Secrets()), config.modele, analyses, echecs, signaux, execution_id)

resultat = SyntheseVeille(
    date=date.today(), execution_id=execution_id, marques_analysees=[a.marque for a in analyses],
    echecs=echecs, signaux=signaux, synthese=synthese,
)
print(resultat.model_dump_json(indent=2))
print(f"\nSynthèse enregistrée : {enregistrer_synthese(resultat)}")