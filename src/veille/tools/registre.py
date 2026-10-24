import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from apify_client import ApifyClient
from pydantic import BaseModel, ValidationError

from veille.llm.client import AppelOutil
from veille.tools.meta import (
    OUTIL_CHERCHER_PUBS_META,
    ArgsChercherPubsMeta,
    chercher_pubs_meta,
)
from veille.tools.tiktok import (
    OUTIL_CHERCHER_PUBS_TIKTOK,
    ArgsChercherPubsTiktok,
    chercher_pubs_tiktok,
)
from veille.tools.web import OUTIL_LIRE_PAGE_WEB, ArgsLirePageWeb, lire_page_web
from veille.traces import span


@dataclass
class Outil:
    schema: dict                    # ce qu'on envoie au LLM (OUTIL_...)
    args: type[BaseModel]           # ce qui valide les arguments du LLM (Args...)
    fonction: Callable[..., dict]   # ce qui fait le travail, dépendances déjà injectées

    @property
    def nom(self) -> str:
        return self.schema["function"]["name"]


def creer_outils(client_apify: ApifyClient, actifs: list[str] | None = None) -> dict[str, Outil]:
    outils = [
        Outil(OUTIL_LIRE_PAGE_WEB, ArgsLirePageWeb, lire_page_web),
        Outil(OUTIL_CHERCHER_PUBS_META, ArgsChercherPubsMeta, partial(chercher_pubs_meta, client=client_apify)),
        Outil(OUTIL_CHERCHER_PUBS_TIKTOK, ArgsChercherPubsTiktok, partial(chercher_pubs_tiktok, client=client_apify)),
    ]
    return {o.nom: o for o in outils if actifs is None or o.nom in actifs}


def resumer_erreurs(erreur: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(morceau) for morceau in e['loc']) or 'arguments'} : {e['msg']}"
        for e in erreur.errors()
    )


def executer_appel_outil(appel: AppelOutil, outils: dict[str, Outil]) -> str:
    # Un span par appel d'outil : durée, issue, taille du résultat (ce qu'il ajoutera au contexte du LLM).
    with span("outil", appel.nom, arguments=appel.arguments[:300]) as attributs:
        outil = outils.get(appel.nom)
        if outil is None:
            attributs["resultat"] = "outil_inconnu"
            resultat = {"erreur": f"L'outil « {appel.nom} » n'existe pas. Outils disponibles : {', '.join(outils)}."}
            return json.dumps(resultat, ensure_ascii=False)

        try:
            args = outil.args.model_validate_json(appel.arguments)
        except ValidationError as erreur:
            attributs["resultat"] = "arguments_invalides"
            resultat = {"erreur": f"Arguments invalides pour {appel.nom} : {resumer_erreurs(erreur)}. Corrige-les et réessaie."}
            return json.dumps(resultat, ensure_ascii=False)

        resultat = outil.fonction(**args.model_dump())   # une exception est notée par le span, puis remonte
        texte = json.dumps(resultat, ensure_ascii=False)
        attributs["resultat"] = "erreur" if "erreur" in resultat else "ok"
        attributs["caracteres"] = len(texte)
        return texte
