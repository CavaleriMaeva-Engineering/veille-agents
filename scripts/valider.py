"""Relire les envois Slack en attente, puis les approuver ou les rejeter.

    uv run python scripts/valider.py                      # liste les envois en attente
    uv run python scripts/valider.py --approuver 3fa9c2d1
    uv run python scripts/valider.py --rejeter 3fa9c2d1 --motif "TikTok en panne, on attend demain"
"""

import argparse
import getpass

from veille.livrables.slack import envoyer_slack
from veille.livrables.validation import decider, lister_en_attente
from veille.settings import Secrets

parser = argparse.ArgumentParser(description="Validation humaine des envois Slack")
groupe = parser.add_mutually_exclusive_group()
groupe.add_argument("--approuver", metavar="ID")
groupe.add_argument("--rejeter", metavar="ID")
parser.add_argument("--motif", help="raison du rejet, gardée dans l'historique")
args = parser.parse_args()

if not args.approuver and not args.rejeter:
    envois = lister_en_attente()
    if not envois:
        print("Aucun envoi en attente.")
    for envoi in envois:
        print(f"\n=== Envoi {envoi.id} (créé le {envoi.cree_le:%d/%m %H:%M}) ===")
        print("Pourquoi il attend une relecture :")
        for raison in envoi.raisons:
            print(f"  - {raison}")
        if envoi.chemin_pdf:
            print(f"PDF à relire : {envoi.chemin_pdf}")
        for bloc in envoi.message.get("blocks", []):
            texte = bloc.get("text", {}).get("text") or " ".join(e.get("text", "") for e in bloc.get("elements", []))
            print(f"  | {texte}")
    raise SystemExit(0)

webhook = Secrets().slack_webhook_url
if webhook is None:
    raise SystemExit("Pas de SLACK_WEBHOOK_URL dans .env : impossible d'envoyer.")

identifiant = args.approuver or args.rejeter
try:
    envoi = decider(
        identifiant, approuver=bool(args.approuver), par=getpass.getuser(), motif=args.motif,
        envoyer=lambda message: envoyer_slack(message, webhook.get_secret_value()),
    )
except ValueError as erreur:
    raise SystemExit(str(erreur)) from erreur
print(f"Envoi {envoi.id} : {envoi.statut} par {envoi.decide_par}.")
