import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

from apify_client import ApifyClient
from apify_client.errors import ApifyApiError
from pydantic import BaseModel, Field

from veille.tools.base import decrire_outil

logger = logging.getLogger(__name__)


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


class ArgsChercherPubsMeta(BaseModel):
    marque: str = Field(
        description="Nom exact de la page Facebook de la marque, tel qu'il apparaît sur Meta (ex. : Typology)."
    )
    max_pubs: int = Field(
        10,
        ge=1,
        le=20,
        description="Nombre maximum de publicités à récupérer. Chaque pub a un coût : demande-en peu si quelques exemples suffisent.",
    )


OUTIL_CHERCHER_PUBS_META = decrire_outil(
    nom="chercher_pubs_meta",
    description=(
        "Cherche les publicités actuellement actives d'une marque concurrente en France dans la "
        "Bibliothèque publicitaire Meta (Facebook, Instagram, Messenger). À utiliser pour savoir "
        "ce qu'une marque met en avant en ce moment : produits, messages, offres, formats. "
        "Renvoie pour chaque pub : ses textes, sa date de début, ses plateformes, son format, "
        "son lien et son bouton d'action. Seules les pubs publiées par la page portant exactement "
        "le nom de la marque sont gardées. Si aucune pub n'est trouvée, ce n'est pas une erreur : "
        "la marque ne diffuse simplement pas de pub active sur Meta en France aujourd'hui, "
        "ne relance pas l'outil."
    ),
    args=ArgsChercherPubsMeta,
)


def est_un_vrai_texte(texte: str | None) -> bool:
    # Cas 1 : il n'y a pas de texte
    if texte is None:
        return False
    # Cas 2 : le texte est vide ou ne contient que des espaces
    if texte.strip() == "":
        return False
    # Cas 3 : c'est un modèle, comme « {{product.brand}} »
    return "{{" not in texte


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


def chercher_pubs_meta(marque: str, client: ApifyClient, max_pubs: int = 10) -> dict:
    parametres = {"active_status": "active", "ad_type": "all", "country": "FR",
                  "search_type": "keyword_unordered", "q": marque}
    url = "https://www.facebook.com/ads/library/?" + urlencode(parametres)

    try:
        execution = client.actor("apify/facebook-ads-scraper").call(
            run_input={"startUrls": [{"url": url}], "resultsLimit": max_pubs},
            max_items=max_pubs,
            wait_duration=timedelta(minutes=3),
        )
    except ApifyApiError as erreur:
        logger.warning(json.dumps({
            "evenement": "erreur_outil",
            "outil": "chercher_pubs_tiktok",
            "code": erreur.status_code,
            "type": erreur.type,
            "message": erreur.message,
        }, ensure_ascii=False))
        return {"erreur": "La bibliothèque publicitaire de Meta est indisponible pour le moment. Utilise une autre source."}
    
    if execution is None or execution.status != "SUCCEEDED":
        return {"erreur": "La collecte des pubs Meta n'a pas abouti à temps. Réessaie plus tard ou utilise une autre source."}

    brutes = client.dataset(execution.default_dataset_id).list_items().items

    pubs = [
        normaliser_pub_meta(brute)
        for brute in brutes
        if (brute.get("pageName") or "").lower() == marque.lower()
    ]

    resultat = {
        "marque": marque,
        "nb_pubs": len(pubs),
        "pubs": [pub.model_dump(mode="json") for pub in pubs],
    }
    if not pubs:
        resultat["remarque"] = (
            f"Aucune pub active de la page '{marque}' trouvée en France "
            f"({len(brutes)} pubs trouvées au total, d'autres pages). "
            "Ce n'est pas une erreur : ne relance pas l'outil."
        )
    return resultat
