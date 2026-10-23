import json
from collections import Counter
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

SOURCE_PAR_OUTIL = {"chercher_pubs_meta": "meta", "chercher_pubs_tiktok": "tiktok", "lire_page_web": "site"}


class PubDurable(BaseModel):
    source: str
    texte: str | None
    duree_jours: int
    lien: str | None


class Signaux(BaseModel):
    nb_pubs: dict[str, int]                 # par source, ex. {"meta": 5, "tiktok": 3}
    formats: dict[str, int]                 # ex. {"VIDEO": 4, "IMAGE": 2, "DCO": 1}
    pub_la_plus_durable: PubDurable | None
    sources_en_erreur: list[str]
    sources_collectees: list[str] = Field(default_factory=list)   # sources qui ont réellement fourni des données


def sans_parametres(url: str | None) -> str | None:
    if not url:
        return None
    morceaux = urlsplit(url)
    return urlunsplit((morceaux.scheme, morceaux.netloc, morceaux.path, "", ""))


def extraire_resultats(messages: list[dict]) -> list[tuple[str, dict]]:
    noms_par_id = {}
    resultats = []
    for message in messages:
        for appel in message.get("tool_calls", []):
            noms_par_id[appel["id"]] = appel["function"]["name"]
        if message["role"] == "tool":
            nom = noms_par_id.get(message["tool_call_id"], "inconnu")
            resultats.append((nom, json.loads(message["content"])))
    return resultats


def lister_sources_collectees(resultats: list[tuple[str, dict]]) -> list[str]:
    sources = []
    for outil, donnees in resultats:
        source = SOURCE_PAR_OUTIL.get(outil, outil)
        a_des_donnees = "erreur" not in donnees and (source == "site" or bool(donnees.get("pubs")))
        if a_des_donnees and source not in sources:
            sources.append(source)
    return sources


def calculer_signaux(resultats: list[tuple[str, dict]]) -> Signaux:
    nb_pubs: Counter = Counter()
    formats: Counter = Counter()
    sources_en_erreur = []
    meilleure: PubDurable | None = None

    for outil, donnees in resultats:
        source = SOURCE_PAR_OUTIL.get(outil, outil)
        if "erreur" in donnees:
            sources_en_erreur.append(source)
            continue
        for pub in donnees.get("pubs", []):
            nb_pubs[source] += 1
            if pub.get("format"):
                formats[pub["format"]] += 1
            duree = pub.get("duree_jours")
            if duree is not None and (meilleure is None or duree > meilleure.duree_jours):
                meilleure = PubDurable(
                    source=source,
                    texte=(pub.get("textes") or [None])[0],
                    duree_jours=duree,
                    lien=sans_parametres(pub.get("lien")),
                )

    return Signaux(
        nb_pubs=dict(nb_pubs),
        formats=dict(formats),
        pub_la_plus_durable=meilleure,
        sources_en_erreur=sources_en_erreur,
        sources_collectees=lister_sources_collectees(resultats),
    )