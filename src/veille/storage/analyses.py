from pathlib import Path

from pydantic import ValidationError

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
    chemin = dossier / f"{synthese.horodatage:%Y-%m-%dT%H-%M-%S}_synthese-marche_{synthese.execution_id}.json"
    chemin.write_text(synthese.model_dump_json(indent=2), encoding="utf-8")
    return chemin


def charger_dernieres_analyses(
    marques: list[str], dossier: Path = DOSSIER_SORTIES
) -> tuple[list[AnalyseMarque], dict[str, str]]:
    analyses, manquantes = [], {}
    for marque in marques:
        chemins = lister_analyses(marque, dossier)
        if not chemins:
            manquantes[marque] = "aucune analyse enregistrée"
            continue
        try:
            analyses.append(charger_analyse(chemins[-1]))
        except ValidationError:
            manquantes[marque] = "analyse enregistrée dans un ancien format"
    return analyses, manquantes


def charger_derniere_synthese(dossier: Path = DOSSIER_SORTIES) -> SyntheseVeille | None:
    chemins = sorted(dossier.glob("*_synthese-marche_*.json"))
    if not chemins:
        return None
    return SyntheseVeille.model_validate_json(chemins[-1].read_text(encoding="utf-8"))


def charger_derniere_analyse(marque: str, dossier: Path = DOSSIER_SORTIES) -> AnalyseMarque | None:
    for chemin in reversed(lister_analyses(marque, dossier)):
        try:
            return charger_analyse(chemin)
        except ValidationError:
            continue
    return None