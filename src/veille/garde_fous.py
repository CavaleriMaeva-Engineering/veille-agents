"""Garde-fous sur 3 niveaux.

- Entrée : le contenu collecté sur le web peut contenir une injection indirecte (« ignore tes instructions… »).
  On retire les phrases suspectes AVANT qu'elles n'entrent dans le contexte du LLM.
- Action : le code encadre chaque appel d'outil. Domaine imposé, pages lisibles limitées au site et aux liens
  des pubs collectées, budget d'appels par outil. Même un LLM détourné ne peut rien faire d'autre.
- Sortie : chaque chiffre d'un constat doit apparaître dans les données (vérification d'ancrage).

La détection par motifs (entrée) est la couche la plus faible : une paraphrase ou une autre langue passe.
Ce sont les limites de privilèges (action) qui protègent vraiment : défense en profondeur.
"""

import json
import logging
import re
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit

from veille.agents.rapport import SECTIONS_CONSTATS, RapportVeille
from veille.agents.signaux import Signaux, sans_parametres
from veille.settings import Marque
from veille.tools.registre import Outil

logger = logging.getLogger(__name__)

# --- Entrée : injection indirecte -------------------------------------------------------------

MOTIFS_INJECTION = [
    r"ignor\w*\s+(?:\w+\s+){0,3}(?:instructions|consignes|r[eè]gles)",
    r"(?:ignore|disregard|forget)\s+(?:\w+\s+){0,3}(?:instructions|rules|prompt)",
    r"(?:system|syst[eè]me)\s*prompt",
    r"tu\s+es\s+(?:maintenant|d[ée]sormais)",
    r"you\s+are\s+now",
    r"(?:nouvelles?|new)\s+instructions?",
    r"(?:appelle|utilise|call|use)\s+(?:l'|the\s+)?(?:outil|tool)",
    r"</?\s*(?:system|assistant|user|historique|extraits|instructions?)\s*>",   # tenter de sortir de nos balises
]
REGEX_INJECTION = re.compile("|".join(f"(?:{m})" for m in MOTIFS_INJECTION), re.IGNORECASE)


def neutraliser(texte: str) -> tuple[str, int]:
    """Retire chaque PHRASE qui contient un motif d'injection (pas seulement les mots : la suite de l'ordre part aussi)."""
    phrases = re.split(r"(?<=[.!?\n])\s+", texte)
    gardees = [p for p in phrases if not REGEX_INJECTION.search(p)]
    retirees = len(phrases) - len(gardees)
    if retirees:
        gardees.append(f"[{retirees} phrase(s) suspecte(s) retirée(s)]")
    return " ".join(gardees), retirees


def neutraliser_donnees(donnees):
    """Applique neutraliser à toutes les chaînes d'un résultat d'outil (dictionnaires et listes imbriqués)."""
    if isinstance(donnees, str):
        return neutraliser(donnees)
    if isinstance(donnees, dict):
        total, propre = 0, {}
        for cle, valeur in donnees.items():
            propre[cle], nb = neutraliser_donnees(valeur)
            total += nb
        return propre, total
    if isinstance(donnees, list):
        total, propre = 0, []
        for valeur in donnees:
            nettoye, nb = neutraliser_donnees(valeur)
            propre.append(nettoye)
            total += nb
        return propre, total
    return donnees, 0


# --- Action : encadrer les appels d'outils ----------------------------------------------------

MAX_APPELS_PAR_OUTIL = {"chercher_pubs_meta": 2, "chercher_pubs_tiktok": 2, "lire_page_web": 2}
MAX_PUBS = 5
OUTILS_DE_PUBS = {"chercher_pubs_meta", "chercher_pubs_tiktok"}


def domaine_de(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def normaliser_url(url: str) -> str:
    return (sans_parametres(url) or "").rstrip("/").replace("://www.", "://")


@dataclass
class Garde:
    marque: Marque
    execution_id: str
    liens_autorises: set[str] = field(default_factory=set)   # liens des pubs collectées, sur le site de la marque
    nb_appels: Counter = field(default_factory=Counter)
    incidents: list[str] = field(default_factory=list)
    verrou: threading.Lock = field(default_factory=threading.Lock)   # les outils tournent en parallèle

    @property
    def domaine(self) -> str:
        return domaine_de(str(self.marque.site))

    def pages_autorisees(self) -> set[str]:
        return {normaliser_url(str(self.marque.site))} | self.liens_autorises

    def signaler(self, evenement: str, detail: str, alerte: bool = True) -> None:
        """alerte=True : l'incident baisse la confiance (PJ10) ; False : simplement journalisé."""
        if alerte:
            with self.verrou:
                self.incidents.append(detail)
        logger.warning(json.dumps({
            "evenement": evenement, "execution_id": self.execution_id, "marque": self.marque.nom, "detail": detail,
        }, ensure_ascii=False))

    def proteger(self, outils: dict[str, Outil]) -> dict[str, Outil]:
        return {nom: replace(outil, fonction=self.envelopper(nom, outil.fonction)) for nom, outil in outils.items()}

    def envelopper(self, nom: str, fonction):
        def appel(**args) -> dict:
            with self.verrou:
                self.nb_appels[nom] += 1
                rang = self.nb_appels[nom]
            limite = MAX_APPELS_PAR_OUTIL.get(nom)
            if limite is not None and rang > limite:
                self.signaler("appel_refuse", f"{nom} : budget de {limite} appels dépassé")
                return {"erreur": f"Budget atteint : {limite} appels au plus à {nom}. Donne ta réponse avec ce que tu as."}

            if nom == "lire_page_web" and normaliser_url(args.get("url", "")) not in self.pages_autorisees():
                self.signaler("appel_refuse", f"lire_page_web : adresse non autorisée ({args.get('url')})")
                return {"erreur": "Adresse non autorisée. Tu peux lire seulement : "
                        + ", ".join(sorted(self.pages_autorisees())) + "."}

            if nom in OUTILS_DE_PUBS:
                args = self.corriger(nom, args)

            resultat, nb_suspectes = neutraliser_donnees(fonction(**args))
            if nb_suspectes:
                self.signaler("injection_neutralisee", f"{nom} : {nb_suspectes} phrase(s) suspecte(s) retirée(s)")
            if nom in OUTILS_DE_PUBS and isinstance(resultat, dict):
                with self.verrou:
                    for pub in resultat.get("pubs", []):
                        if pub.get("lien") and domaine_de(pub["lien"]) == self.domaine:
                            self.liens_autorises.add(normaliser_url(pub["lien"]))
            return resultat

        return appel

    def corriger(self, nom: str, args: dict) -> dict:
        """Ce que le code connaît déjà ne se laisse pas au LLM : le domaine vient de la config."""
        corriges = dict(args)
        if "domaine" in args and args["domaine"] != self.domaine:
            if args["domaine"] is not None:
                self.signaler(
                    "argument_corrige", f"{nom} : domaine {args['domaine']} remplacé par {self.domaine}", alerte=False
                )
            corriges["domaine"] = self.domaine
        if "max_pubs" in args:
            corriges["max_pubs"] = min(args["max_pubs"], MAX_PUBS)
        return corriges


# --- Sortie : vérification d'ancrage ----------------------------------------------------------

REGEX_NOMBRE = re.compile(r"\d+(?:[.,]\d+)?")


def nombres(texte: str) -> set[str]:
    return {n.replace(",", ".") for n in REGEX_NOMBRE.findall(texte)}


def verifier_ancrage(
    rapport: RapportVeille, observations: list[str], signaux: Signaux, memoire: str | None = None
) -> tuple[RapportVeille, list[str]]:
    """Un constat dont un chiffre (prix, durée, quantité) n'apparaît nulle part dans les données est retiré.

    Limite : on vérifie les chiffres, pas le sens. « 75 € » peut être présent dans les données mais attribué
    au mauvais produit ; ça, c'est le rôle des évals (faithfulness, PJ13)."""
    connus = nombres(" ".join(observations)) | nombres(signaux.model_dump_json()) | nombres(memoire or "")
    corrections, retires = {}, []
    for champ in SECTIONS_CONSTATS:
        gardes = []
        for constat in getattr(rapport, champ):
            inconnus = nombres(constat.affirmation) - connus
            if inconnus:
                retires.append(f"constat retiré, chiffres absents des données ({', '.join(sorted(inconnus))}) : "
                               f"{constat.affirmation}")
            else:
                gardes.append(constat)
        corrections[champ] = gardes
    return rapport.model_copy(update=corrections), retires
