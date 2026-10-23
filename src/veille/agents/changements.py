from pydantic import BaseModel, Field

from veille.agents.signaux import Signaux

SEUIL_CHANGEMENT = 0.3   # à partir de 30 % de pubs renouvelées, le changement compte


class Changements(BaseModel):
    comparable: bool                     # False : aucune veille précédente exploitable
    nouvelles_pubs: list[str] = Field(default_factory=list)
    pubs_disparues: list[str] = Field(default_factory=list)   # sorties de l'échantillon, pas forcément arrêtées
    nouveaux_formats: list[str] = Field(default_factory=list)
    nouvelles_pages: list[str] = Field(default_factory=list)
    score: float = 0.0                   # part des pubs renouvelées, entre 0 et 1
    significatif: bool = True            # sans comparaison possible, tout est nouveau


def comparer(actuels: Signaux, precedents: Signaux | None) -> Changements:
    if precedents is None or precedents.ids_pubs is None:
        return Changements(comparable=False)

    # Une source en panne aujourd'hui (ou la dernière fois) fausserait la comparaison :
    # on ne compare que les sources collectées les deux fois.
    communes = set(actuels.sources_collectees) & set(precedents.sources_collectees)

    def filtrer(ids: list[str] | None) -> set[str]:
        return {i for i in ids or [] if i.split(":", 1)[0] in communes}

    avant, apres = filtrer(precedents.ids_pubs), filtrer(actuels.ids_pubs)
    nouvelles, disparues = sorted(apres - avant), sorted(avant - apres)
    union = avant | apres
    score = (len(nouvelles) + len(disparues)) / len(union) if union else 0.0

    nouveaux_formats = sorted(set(actuels.formats) - set(precedents.formats))
    nouvelles_pages = sorted(set(actuels.pages_destination or []) - set(precedents.pages_destination or []))

    return Changements(
        comparable=True,
        nouvelles_pubs=nouvelles,
        pubs_disparues=disparues,
        nouveaux_formats=nouveaux_formats,
        nouvelles_pages=nouvelles_pages,
        score=round(score, 2),
        significatif=score >= SEUIL_CHANGEMENT or bool(nouveaux_formats) or bool(nouvelles_pages),
    )