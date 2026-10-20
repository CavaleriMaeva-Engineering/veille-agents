import json
from pathlib import Path

from apify_client import ApifyClient

from veille.settings import Secrets, charger_config

secrets = Secrets()
config = charger_config()
marque = config.marques[0]

url = (
    "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
    f"&country=FR&search_type=keyword_unordered&q={marque.nom}"
)

client = ApifyClient(secrets.apify_token.get_secret_value())
execution = client.actor("apify/facebook-ads-scraper").call(
    run_input={"startUrls": [{"url": url}], "resultsLimit": 5}
)

pubs = client.dataset(execution.default_dataset_id).list_items().items

dossier = Path("tests/donnees")
dossier.mkdir(parents=True, exist_ok=True)
fichier = dossier / f"meta_{marque.nom.lower()}.json"
fichier.write_text(json.dumps(pubs, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"{len(pubs)} pubs enregistrées dans {fichier}")