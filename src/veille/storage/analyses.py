from pathlib import Path

from veille.agents.analyste import AnalyseMarque
from veille.agents.synthese import SyntheseVeille

DOSSIER_SORTIES = Path("sorties")


def nom_de_fichier(analyse: AnalyseMarque) -> str:
    marque = analyse.marque.lower().replace(" ", "-")
    return f"{analyse.horodatage:%Y-%m-%dT%H-%M-%S}_{marque}_{analyse.execution_id}.json"


def enregistrer_analyse(analyse: AnalyseMarque, dossier: Path = DOSSIER_SORTIES) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / nom_de_fichier(analyse)
    chemin.write_text(analyse.model_dump_json(indent=2), encoding="utf-8")
    return chemin


def charger_analyse(chemin: Path) -> AnalyseMarque:
    return AnalyseMarque.model_validate_json(chemin.read_text(encoding="utf-8"))


def lister_analyses(marque: str, dossier: Path = DOSSIER_SORTIES) -> list[Path]:
    motif = f"*_{marque.lower().replace(' ', '-')}_*.json"
    return sorted(dossier.glob(motif))


def enregistrer_synthese(synthese: SyntheseVeille, dossier: Path = DOSSIER_SORTIES) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{synthese.date.isoformat()}_synthese-marche_{synthese.execution_id}.json"
    chemin.write_text(synthese.model_dump_json(indent=2), encoding="utf-8")
    return chemin