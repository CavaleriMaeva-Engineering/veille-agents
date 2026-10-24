import json
import logging
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from apify_client import ApifyClient
from apify_client.errors import ApifyApiError
from pydantic import BaseModel, Field

from veille.tools.base import decrire_outil, est_du_domaine, noter_cout_apify

logger = logging.getLogger(__name__)


class PubMeta(BaseModel):
    id: str
    marque: str
    date_debut: datetime | None  # Le champ est obligatoire mais peut valoir None
    duree_jours: int | None   # jours de diffusion jusqu'à aujourd'hui, calculés par le code
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
    domaine: str | None = Field(
        None, description="Site officiel de la marque, sans https ni www (ex. : typology.com). Améliore le filtrage."
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

def normaliser_pub_meta(brute: dict, aujourd_hui: date | None = None) -> PubMeta:
    aujourd_hui = aujourd_hui or date.today()
    debut = brute.get("startDateFormatted")
    duree = (aujourd_hui - datetime.fromisoformat(debut).date()).days + 1 if debut else None
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
        duree_jours=duree,
        active=bool(brute.get("isActive")),
        plateformes=brute.get("publisherPlatform") or [],
        format=snapshot.get("displayFormat"),
        lien=snapshot.get("linkUrl"),
        textes=textes,
        appel_a_l_action=snapshot.get("ctaText"),
    )


def chercher_pubs_meta(marque: str, client: ApifyClient, max_pubs: int = 10, domaine: str | None = None) -> dict:
    parametres = {"active_status": "active", "ad_type": "all", "country": "FR",
                  "search_type": "keyword_unordered", "q": marque}
    url = "https://www.facebook.com/ads/library/?" + urlencode(parametres)
    a_chercher = min(max_pubs * 3, 15)   # on filtre ensuite : chercher plus large que ce qu'on garde

    try:
        execution = client.actor("apify/facebook-ads-scraper").call(
            run_input={"startUrls": [{"url": url}], "resultsLimit": a_chercher},
            max_items=a_chercher,
            wait_duration=timedelta(minutes=3),
        )
    except ApifyApiError as erreur:
        logger.warning(json.dumps({
            "evenement": "erreur_outil",
            "outil": "chercher_pubs_meta",
            "code": erreur.status_code,
            "type": erreur.type,
            "message": erreur.message,
        }, ensure_ascii=False))
        return {"erreur": "La bibliothèque publicitaire de Meta est indisponible pour le moment. Utilise une autre source."}

    noter_cout_apify(execution)   # PJ15 : le coût du run Apify rejoint le span de l'outil
    if execution is None or execution.status != "SUCCEEDED":
        return {"erreur": "La collecte des pubs Meta n'a pas abouti à temps. Réessaie plus tard ou utilise une autre source."}

    brutes = client.dataset(execution.default_dataset_id).list_items().items

    def est_de_la_marque(pub: PubMeta) -> bool:
        return pub.marque.lower() == marque.lower() or (domaine is not None and est_du_domaine(pub.lien, domaine))

    pubs = [pub for pub in (normaliser_pub_meta(brute) for brute in brutes) if est_de_la_marque(pub)][:max_pubs]

    resultat = {
        "marque": marque,
        "nb_pubs": len(pubs),
        "pubs": [pub.model_dump(mode="json") for pub in pubs],
    }
    if not pubs:
        resultat["remarque"] = (
            f"Aucune pub active de la marque '{marque}' trouvée en France "
            f"({len(brutes)} pubs trouvées au total, d'autres annonceurs). "
            "Ce n'est pas une erreur : ne relance pas l'outil."
        )
    return resultat
