from datetime import date

from pydantic import BaseModel

from veille.tools.meta import est_un_vrai_texte


class PubTiktok(BaseModel):
    id: str
    marque: str
    annonceur: str | None
    date_debut: date | None
    date_derniere_diffusion: date | None
    duree_jours: int | None
    active: bool
    format: str | None
    textes: list[str]
    lien: str | None
    appel_a_l_action: str | None
    impressions: str | None
    objectif: str | None
    ciblage_age: list[str]
    ciblage_genre: list[str]


def normaliser_pub_tiktok(brute: dict, marque: str) -> PubTiktok:
    debut = brute.get("adStartDate")
    fin = brute.get("adEndDate")
    duree = (
        (date.fromisoformat(fin) - date.fromisoformat(debut)).days + 1
        if debut and fin
        else None
    )

    titre = brute.get("adTitle")
    textes = [titre] if est_un_vrai_texte(titre) else []

    return PubTiktok(
        id=brute["adId"],
        marque=marque,
        annonceur=brute.get("advertiserName"),
        date_debut=debut,
        date_derniere_diffusion=fin,
        duree_jours=duree,
        active=brute.get("status") == "active",
        format=brute.get("adType"),
        textes=textes,
        lien=brute.get("landingPageUrl"),
        appel_a_l_action=brute.get("callToAction"),
        impressions=brute.get("adImpressions"),
        objectif=brute.get("advertisingObjective"),
        ciblage_age=brute.get("targetingByAge") or [],
        ciblage_genre=brute.get("targetingByGender") or [],
    )