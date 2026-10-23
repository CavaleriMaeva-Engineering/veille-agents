import argparse
import json
from datetime import date, datetime

from veille.livrables.pdf import generer_pdf
from veille.livrables.slack import construire_message, envoyer_slack
from veille.livrables.validation import (
    creer_envoi,
    enregistrer_envoi,
    evaluer_confiance,
)
from veille.settings import Secrets, charger_config
from veille.storage.analyses import (
    DOSSIER_SORTIES,
    charger_derniere_synthese,
    charger_dernieres_analyses,
)

parser = argparse.ArgumentParser(description="Générer le PDF et publier le résumé sur Slack")
parser.add_argument("--relecture", action="store_true", help="toujours passer par la validation humaine")
args = parser.parse_args()

synthese = charger_derniere_synthese()
if synthese is None:
    raise SystemExit("Aucune synthèse enregistrée : lance d'abord scripts/synthese_marche.py")

analyses, _ = charger_dernieres_analyses([m.nom for m in charger_config().marques])
chemin_pdf = generer_pdf(synthese, analyses, DOSSIER_SORTIES / f"{datetime.now():%Y-%m-%dT%H-%M-%S}_rapport-veille.pdf")
print(f"Rapport généré : {chemin_pdf}")

message = construire_message(synthese, chemin_pdf)

confiance = evaluer_confiance(synthese, analyses, date.today())
if args.relecture or not confiance.haute:
    raisons = confiance.raisons or ["relecture demandée (--relecture)"]
    envoi = creer_envoi(message, chemin_pdf, raisons)
    chemin = enregistrer_envoi(envoi)
    print(f"Confiance basse : envoi {envoi.id} mis en attente de validation ({chemin}).")
    for raison in raisons:
        print(f"  - {raison}")
    print(f"Relire : uv run python scripts/valider.py   puis   --approuver {envoi.id}  ou  --rejeter {envoi.id}")
    raise SystemExit(0)

print("Confiance haute : envoi direct.")
webhook = Secrets().slack_webhook_url
if webhook is None:
    print("Pas de SLACK_WEBHOOK_URL : voici le message qui serait envoyé.")
    print(json.dumps(message, ensure_ascii=False, indent=2))
else:
    envoyer_slack(message, webhook.get_secret_value())
    print("Message envoyé sur Slack.")