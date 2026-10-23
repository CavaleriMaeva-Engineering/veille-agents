from datetime import datetime

from veille.livrables.pdf import generer_pdf
from veille.settings import charger_config
from veille.storage.analyses import (
    DOSSIER_SORTIES,
    charger_derniere_synthese,
    charger_dernieres_analyses,
)

synthese = charger_derniere_synthese()
if synthese is None:
    raise SystemExit("Aucune synthèse enregistrée : lance d'abord scripts/synthese_marche.py")

analyses, _ = charger_dernieres_analyses([m.nom for m in charger_config().marques])
chemin = DOSSIER_SORTIES / f"{datetime.now():%Y-%m-%dT%H-%M-%S}_rapport-veille.pdf"
print(f"Rapport généré : {generer_pdf(synthese, analyses, chemin)}")