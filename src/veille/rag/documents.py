"""Découpage de l'historique de veille en morceaux (chunks) à indexer.

Chunking structurel : une pub = un morceau, un constat de rapport = un morceau.
Seul le texte libre (pages web) est découpé en fenêtres de taille fixe avec recouvrement.
"""

import hashlib
import json
import logging
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from veille.agents.analyste import AnalyseMarque
from veille.agents.signaux import sans_parametres

logger = logging.getLogger(__name__)

TAILLE_MORCEAU = 600   # caractères : environ 150 tokens, assez pour un paragraphe de page produit
RECOUVREMENT = 100     # une phrase coupée en deux reste entière dans l'un des deux morceaux

CATEGORIES_CONSTATS = {
    "produits_pousses": "produit poussé",
    "messages_et_promesses": "message ou promesse",
    "offres": "offre",
    "formats_et_plateformes": "format ou plateforme",
    "cible": "cible",
}


class Morceau(BaseModel):
    id: str                 # stable : le même contenu garde le même id d'une veille à l'autre
    texte: str              # ce qui est indexé et montré au LLM
    marque: str
    type: Literal["pub", "page", "constat"]
    source: str             # meta, tiktok, site, ou les sources d'un constat
    date: date              # dernière veille où ce contenu a été vu
    vu_le: list[date] = Field(default_factory=list)
    lien: str | None = None


def empreinte(*parties: str) -> str:
    return hashlib.sha1("|".join(parties).encode("utf-8")).hexdigest()[:12]


def decouper_texte(texte: str, taille: int = TAILLE_MORCEAU, recouvrement: int = RECOUVREMENT) -> list[str]:
    texte = " ".join(texte.split())   # espaces et retours à la ligne normalisés
    if len(texte) <= taille:
        return [texte] if texte else []
    morceaux, debut = [], 0
    while True:
        fin = min(debut + taille, len(texte))
        if fin < len(texte):
            espace = texte.rfind(" ", debut, fin)
            if espace > debut + taille // 2:   # on coupe entre deux mots, pas au milieu d'un mot
                fin = espace
        morceaux.append(texte[debut:fin].strip())
        if fin == len(texte):
            return morceaux
        debut = fin - recouvrement
        espace = texte.find(" ", debut, fin)
        if espace != -1:
            debut = espace + 1                 # le morceau suivant commence au début d'un mot


def texte_pub(pub: dict, marque: str, source: str) -> str:
    details = [f"Pub {source} de {marque}"]
    if pub.get("format"):
        details.append(f"format {pub['format']}")
    if pub.get("plateformes"):
        details.append("sur " + ", ".join(p.lower() for p in pub["plateformes"]))
    if pub.get("duree_jours") is not None:
        details.append(f"diffusée depuis {pub['duree_jours']} jours")
    details.append("active" if pub.get("active") else "inactive")
    texte = ", ".join(details) + "."
    if pub.get("textes"):
        texte += " Textes : " + " | ".join(pub["textes"])
    if pub.get("appel_a_l_action"):
        texte += f" Appel à l'action : {pub['appel_a_l_action']}."
    lien = sans_parametres(pub.get("lien"))
    if lien:
        texte += f" Lien : {lien}"
    return texte


def morceaux_depuis_analyse(analyse: AnalyseMarque) -> list[Morceau]:
    commun = {"marque": analyse.marque, "date": analyse.date, "vu_le": [analyse.date]}
    morceaux: list[Morceau] = []

    for observation in analyse.observations:
        try:
            donnees = json.loads(observation)
        except json.JSONDecodeError:
            continue
        if not isinstance(donnees, dict) or "erreur" in donnees:
            continue
        for pub in donnees.get("pubs", []):
            # Limite connue : l'observation ne garde pas le nom de l'outil ; seules les pubs Meta ont des plateformes.
            source = "meta" if "plateformes" in pub else "tiktok"
            morceaux.append(Morceau(
                id=f"pub:{source}:{pub.get('id') or empreinte(json.dumps(pub, sort_keys=True))}",
                texte=texte_pub(pub, analyse.marque, source), type="pub", source=source,
                lien=sans_parametres(pub.get("lien")), **commun,
            ))
        if "url" in donnees and donnees.get("texte"):
            url = sans_parametres(donnees["url"])
            for bout in decouper_texte(donnees["texte"]):
                morceaux.append(Morceau(
                    id=f"page:{empreinte(url or '', bout)}", texte=f"Page du site de {analyse.marque} : {bout}",
                    type="page", source="site", lien=url, **commun,
                ))

    for champ, libelle in CATEGORIES_CONSTATS.items():
        for constat in getattr(analyse.rapport, champ):
            morceaux.append(Morceau(
                id=f"constat:{empreinte(analyse.marque, champ, constat.affirmation)}",
                texte=f"{analyse.marque}, {libelle} : {constat.affirmation}",
                type="constat", source=",".join(constat.sources), **commun,
            ))
    return morceaux


def fusionner(par_id: dict[str, Morceau], morceau: Morceau) -> None:
    """Une même pub revue à chaque veille = un seul morceau, avec la version la plus récente."""
    existant = par_id.get(morceau.id)
    if existant is None:
        par_id[morceau.id] = morceau
        return
    vu_le = sorted(set(existant.vu_le) | set(morceau.vu_le))
    plus_recent = morceau if morceau.date >= existant.date else existant
    par_id[morceau.id] = plus_recent.model_copy(update={"vu_le": vu_le})


def charger_corpus(dossiers: list[Path]) -> tuple[list[Morceau], int]:
    """Tous les morceaux de toutes les analyses enregistrées, et le nombre de fichiers ignorés."""
    par_id: dict[str, Morceau] = {}
    ignores = 0
    for dossier in dossiers:
        for chemin in sorted(dossier.glob("*.json")):
            if "_synthese-marche_" in chemin.name:
                continue
            try:
                analyse = AnalyseMarque.model_validate_json(chemin.read_text(encoding="utf-8"))
            except ValidationError:
                ignores += 1   # analyse enregistrée dans un ancien format
                continue
            for morceau in morceaux_depuis_analyse(analyse):
                fusionner(par_id, morceau)
    return list(par_id.values()), ignores
