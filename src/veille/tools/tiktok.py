import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from apify_client import ApifyClient
from apify_client.errors import ApifyApiError
from pydantic import BaseModel, Field

from veille.tools.base import decrire_outil, est_du_domaine, noter_cout_apify
from veille.tools.meta import est_un_vrai_texte

logger = logging.getLogger(__name__)

ACTEUR_TIKTOK = "lentic_clockss/tiktok-ads-top-ads-actor"

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


class ArgsChercherPubsTiktok(BaseModel):
    marque: str = Field(description="Nom de la marque tel qu'il apparaît dans ses publicités (ex. : Typology).")
    domaine: str = Field(description="Site officiel de la marque, sans https ni www (ex. : typology.com).")
    max_pubs: int = Field(3, ge=1, le=3, description="Nombre maximum de publicités à récupérer (3 au plus).")


OUTIL_CHERCHER_PUBS_TIKTOK = decrire_outil(
    nom="chercher_pubs_tiktok",
    description=(
        "Cherche les publicités récentes d'une marque concurrente en France dans la bibliothèque "
        "publicitaire de TikTok. À utiliser pour savoir ce qu'une marque pousse sur TikTok : "
        "produits, messages, offres, cible. Renvoie pour chaque pub : son texte, ses dates de "
        "diffusion, sa durée en jours (plus elle est longue, plus la pub est probablement rentable), "
        "ses impressions, son lien, son objectif et son ciblage par âge et par genre. Sur TikTok, "
        "l'annonceur est souvent la société et non la marque : seules les pubs qui renvoient vers "
        "le site de la marque sont gardées. Si aucune pub n'est trouvée, ce n'est pas une erreur : "
        "ne relance pas l'outil."
    ),
    args=ArgsChercherPubsTiktok,
)


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


def chercher_pubs_tiktok(marque: str, domaine: str, client: ApifyClient, max_pubs: int = 3) -> dict:
    try:
        execution = client.actor(ACTEUR_TIKTOK).call(
            run_input={
                "query": marque,
                "country": "FR",
                "contentType": "ads",
                "includeDetails": True,
                "maxItems": max_pubs,
            },
            max_total_charge_usd=Decimal("0.05"),   # plafond de coût par run, au-dessus du minimum d'Apify
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
        return {"erreur": "La bibliothèque publicitaire TikTok est indisponible pour le moment. Utilise une autre source."}
    
    noter_cout_apify(execution)   # PJ15 : le coût du run Apify rejoint le span de l'outil
    if execution is None or execution.status != "SUCCEEDED":
        return {"erreur": "La collecte des pubs TikTok n'a pas abouti à temps. Réessaie plus tard ou utilise une autre source."}

    brutes = client.dataset(execution.default_dataset_id).list_items().items
    pubs = [
        normaliser_pub_tiktok(brute, marque)
        for brute in brutes
        if est_du_domaine(brute.get("landingPageUrl"), domaine)
    ]

    resultat = {
        "marque": marque,
        "nb_pubs": len(pubs),
        "pubs": [pub.model_dump(mode="json") for pub in pubs],
    }
    if not pubs:
        resultat["remarque"] = (
            f"Aucune pub TikTok active renvoyant vers {domaine} trouvée en France "
            f"({len(brutes)} pubs trouvées au total, d'autres annonceurs). "
            "Ce n'est pas une erreur : ne relance pas l'outil."
        )
    return resultat