from datetime import datetime

from pydantic import BaseModel


class PubMeta(BaseModel):
    id: str
    marque: str
    date_debut: datetime | None  # Le champ est obligatoire mais peut valoir None
    active: bool
    plateformes: list[str]
    format: str | None
    textes: list[str]
    lien: str | None
    appel_a_l_action: str | None


def est_un_vrai_texte(texte: str | None) -> bool:
    # Cas 1 : il n'y a pas de texte
    if texte is None:
        return False
    # Cas 2 : le texte est vide ou ne contient que des espaces
    if texte.strip() == "":
        return False
    # Cas 3 : c'est un modèle, comme « {{product.brand}} »
    if "{{" in texte:
        return False
    return True


def normaliser_pub_meta(brute: dict) -> PubMeta:
    snapshot = brute.get("snapshot") or {}
    corps = snapshot.get("body") or {}
    cartes = snapshot.get("cards") or []

    candidats = [snapshot.get("title"), corps.get("text")]
    for carte in cartes:
        candidats.append(carte.get("body"))
        candidats.append(carte.get("title"))

    textes = []
    for candidat in candidats:
        if est_un_vrai_texte(candidat) and candidat not in textes:
            textes.append(candidat)

    return PubMeta(
        id=brute.get("adArchiveID"),
        marque=brute.get("pageName"),
        date_debut=brute.get("startDateFormatted"),
        active=brute.get("isActive"),
        plateformes=brute.get("publisherPlatform") or [],
        format=snapshot.get("displayFormat"),
        lien=snapshot.get("linkUrl"),
        textes=textes,
        appel_a_l_action=snapshot.get("ctaText"),
    )
