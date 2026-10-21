import json
from pathlib import Path

from apify_client import ApifyClient

from veille.settings import Secrets, charger_config

secrets = Secrets()
config = charger_config()
client = ApifyClient(secrets.apify_token.get_secret_value())

dossier = Path("tests/donnees")
dossier.mkdir(parents=True, exist_ok=True)

for marque in config.marques:
    execution = client.actor("lentic_clockss/tiktok-ads-top-ads-actor").call(
        run_input={
            "query": marque.nom,
            "country": "FR",
            "contentType": "ads",
            "includeDetails": True,
            "maxItems": 3,
        }
    )
    pubs = client.dataset(execution.default_dataset_id).list_items().items

    fichier = dossier / f"tiktok_{marque.nom.lower().replace(' ', '_')}.json"
    fichier.write_text(json.dumps(pubs, indent=2, ensure_ascii=False), encoding="utf-8")

    annonceurs = {pub.get("advertiserName") for pub in pubs}
    print(f"{marque.nom} : {len(pubs)} pubs, statut {execution.status}, annonceurs {annonceurs}")