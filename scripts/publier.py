import json
from datetime import datetime

from veille.livrables.pdf import generer_pdf
from veille.livrables.slack import construire_message, envoyer_slack
from veille.settings import Secrets, charger_config
from veille.storage.analyses import (
    DOSSIER_SORTIES,
    charger_derniere_synthese,
    charger_dernieres_analyses,
)

synthese = charger_derniere_synthese()
if synthese is None:
    raise SystemExit("Aucune synthèse enregistrée : lance d'abord scripts/synthese_marche.py")

analyses, _ = charger_dernieres_analyses([m.nom for m in charger_config().marques])
chemin_pdf = generer_pdf(synthese, analyses, DOSSIER_SORTIES / f"{datetime.now():%Y-%m-%dT%H-%M-%S}_rapport-veille.pdf")
print(f"Rapport généré : {chemin_pdf}")

message = construire_message(synthese, chemin_pdf)
webhook = Secrets().slack_webhook_url
if webhook is None:
    print("Pas de SLACK_WEBHOOK_URL : voici le message qui serait envoyé.")
    print(json.dumps(message, ensure_ascii=False, indent=2))
else:
    envoyer_slack(message, webhook.get_secret_value())
    print("Message envoyé sur Slack.")