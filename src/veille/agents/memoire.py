"""Mémoire long terme du rédacteur : ce que l'historique de veille dit déjà de la marque.

Context engineering : on ne donne PAS tout l'historique au rédacteur (trop long, trop cher, et il noierait
les données du jour). On lui donne les changements calculés par le code, puis au plus NB_SOUVENIRS
morceaux d'historique retrouvés par le RAG, chacun coupé à TAILLE_SOUVENIR caractères.
"""

import json
from collections.abc import Callable
from pathlib import Path

from veille.agents.changements import Changements
from veille.rag.documents import Morceau, charger_corpus
from veille.rag.index import Encodeur
from veille.rag.recherche import MoteurRecherche

type Rappel = Callable[[str, str], list[Morceau]]   # (marque, requête) -> souvenirs

NB_SOUVENIRS = 5
TAILLE_SOUVENIR = 300                  # la mémoire complète les données du jour, elle ne doit pas les noyer
# Seulement les pubs : des faits bruts, datés (vu_le), dédoublonnés par leur identifiant.
# Pas les constats : réécrits différemment par le LLM à chaque veille, ils reviennent en 5 versions du même fait
# (constaté sur les vraies données) et propageraient les erreurs du rédacteur. Pas les pages : longues et bruitées.
TYPES_MEMOIRE = {"pub"}


def requete_depuis_collecte(observations: list[str], marque: str) -> str:
    """La requête de mémoire = les textes des pubs du jour : on cherche ce qui leur ressemble dans le passé."""
    textes: list[str] = []
    for observation in observations:
        try:
            donnees = json.loads(observation)
        except json.JSONDecodeError:
            continue
        if isinstance(donnees, dict):
            for pub in donnees.get("pubs", []):
                textes.extend(pub.get("textes") or [])
    if not textes:
        return f"{marque} produits offres messages promesses"
    return f"{marque} " + " ".join(textes)[:1000]


def construire_rappel(dossiers: list[Path], encodeur: Encodeur) -> Rappel:
    """Le corpus est chargé UNE fois, AVANT la veille : il ne contient donc que les veilles passées,
    y compris celles du jour même (un filtre « avant aujourd'hui » les aurait toutes exclues)."""
    morceaux, _ = charger_corpus(dossiers)
    moteur = MoteurRecherche(morceaux, encodeur)   # hybride sans reranker : un seul modèle à charger

    def rappeler(marque: str, requete: str) -> list[Morceau]:
        resultats = moteur.rechercher(requete, k=NB_SOUVENIRS, marque=marque, mode="hybride", types=TYPES_MEMOIRE)
        return [r.morceau for r in resultats]

    return rappeler


def formater_memoire(souvenirs: list[Morceau], changements: Changements | None) -> str:
    lignes = []
    if changements is not None and changements.comparable:
        lignes.append(
            "Changements calculés depuis la veille précédente (exacts) : "
            f"{len(changements.nouvelles_pubs)} nouvelle(s) pub(s), "
            f"{len(changements.pubs_disparues)} sortie(s) de l'échantillon, "
            f"nouveaux formats : {', '.join(changements.nouveaux_formats) or 'aucun'}, "
            f"nouvelles pages de destination : {', '.join(changements.nouvelles_pages) or 'aucune'}."
        )
    elif changements is not None:
        lignes.append("Pas de veille précédente comparable : aucun changement chiffré.")
    if souvenirs:
        lignes.append("Extraits de l'historique :")
    for souvenir in souvenirs:
        periode = souvenir.date.isoformat()
        if souvenir.vu_le and souvenir.vu_le[0] != souvenir.date:
            periode = f"{souvenir.vu_le[0].isoformat()} → {periode}"
        texte = souvenir.texte if len(souvenir.texte) <= TAILLE_SOUVENIR else souvenir.texte[:TAILLE_SOUVENIR] + "…"
        lignes.append(f"- [{souvenir.type}, vu {periode}] {texte}")
    return "\n".join(lignes)
