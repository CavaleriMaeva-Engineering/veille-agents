import json
from collections import Counter
from datetime import date

import groq
from pydantic import BaseModel, ConfigDict, Field

from veille.agents.analyste import AnalyseMarque
from veille.agents.signaux import PubDurable
from veille.llm.structure import generer_structure


class PubDurableMarque(BaseModel):
    marque: str
    pub: PubDurable


class SignauxMarche(BaseModel):
    nb_pubs_par_marque: dict[str, int]
    formats: dict[str, int]
    classement_pubs_durables: list[PubDurableMarque]   # de la plus durable à la moins durable
    marques_sans_pub: list[str]


def calculer_signaux_marche(analyses: list[AnalyseMarque]) -> SignauxMarche:
    formats: Counter = Counter()
    for analyse in analyses:
        formats.update(analyse.signaux.formats)
    durables = [
        PubDurableMarque(marque=a.marque, pub=a.signaux.pub_la_plus_durable)
        for a in analyses
        if a.signaux.pub_la_plus_durable is not None
    ]
    return SignauxMarche(
        nb_pubs_par_marque={a.marque: sum(a.signaux.nb_pubs.values()) for a in analyses},
        formats=dict(formats),
        classement_pubs_durables=sorted(durables, key=lambda d: d.pub.duree_jours, reverse=True),
        marques_sans_pub=[a.marque for a in analyses if sum(a.signaux.nb_pubs.values()) == 0],
    )


class PositionMarque(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marque: str
    positionnement: str = Field(description="En une phrase : ce que la marque met en avant, d'après ses constats.")


class SyntheseMarche(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tendances_communes: list[str] = Field(
        description="Angles, promesses, offres ou formats partagés par au moins deux marques, en citant lesquelles."
    )
    positionnements: list[PositionMarque]
    differences_notables: list[str] = Field(description="Ce qui distingue nettement une marque des autres.")
    limites: list[str] = Field(description="Marques non analysées, sources manquantes. Pas de critique de stratégie.")


PROMPT_SYNTHESE = """Tu rédiges une synthèse de veille publicitaire sur un marché, à partir des analyses de plusieurs marques.
Règles :
- Utilise UNIQUEMENT les analyses et les signaux fournis. N'invente rien.
- Les signaux du marché sont exacts : utilise-les pour les chiffres, ne recalcule rien.
- Une tendance commune doit concerner au moins deux marques, que tu nommes.
- Un positionnement par marque analysée, en une phrase.
- Mentionne dans limites chaque marque non analysée et chaque source manquante.
- Mentionne dans limites chaque marque sans pub trouvée (signal marques_sans_pub) : on ne peut rien conclure sur elle."""

def rediger_synthese(
    client: groq.Groq,
    modele: str,
    analyses: list[AnalyseMarque],
    echecs: dict[str, str],
    signaux: SignauxMarche,
    execution_id: str,
) -> SyntheseMarche:
    resumes = [
        {"marque": a.marque, "signaux": a.signaux.model_dump(mode="json"), "rapport": a.rapport.model_dump(mode="json")}
        for a in analyses
    ]
    messages = [
        {"role": "system", "content": PROMPT_SYNTHESE},
        {
            "role": "user",
            "content": (
                f"Signaux du marché (exacts) :\n{signaux.model_dump_json()}\n\n"
                f"Marques non analysées : {json.dumps(echecs, ensure_ascii=False)}\n\n"
                f"Analyses par marque :\n{json.dumps(resumes, ensure_ascii=False)}"
            ),
        },
    ]
    return generer_structure(client, modele, messages, SyntheseMarche, agent="synthese", execution_id=execution_id)


class SyntheseVeille(BaseModel):
    date: date
    execution_id: str
    marques_analysees: list[str]
    echecs: dict[str, str]
    signaux: SignauxMarche
    synthese: SyntheseMarche