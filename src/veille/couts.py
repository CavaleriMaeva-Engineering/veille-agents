"""Coûts : tarifs, coût d'un appel LLM, et bilan d'une exécution à partir de sa trace.

La trace garde les faits bruts (tokens, durées) ; les prix sont appliqués ici. Si un tarif change,
on recalcule le coût des anciennes exécutions sans les relancer.

Équivalent Anthropic : on applique les tarifs Claude aux MÊMES nombres de tokens. C'est une estimation :
les tokenizers diffèrent (le même texte français ne donne pas le même nombre de tokens), et un autre
modèle ne raisonnerait pas avec la même longueur.
"""

from collections import defaultdict
from dataclasses import dataclass

from pydantic import BaseModel

DATE_TARIFS = "2026-10-23"
SOURCES_TARIFS = [
    "Groq : prix publics des modèles gpt-oss ; jetons lus en cache facturés -50 % (console.groq.com/docs/prompt-caching)",
    "Anthropic : platform.claude.com/docs/en/about-claude/pricing (Haiku 5.5 en dessous de 100k tokens de prompt)",
]


@dataclass(frozen=True)
class Tarif:
    """Prix en dollars par million de tokens."""
    entree: float
    lecture_cache: float
    sortie: float
    ecriture_cache: float | None = None   # Anthropic seulement : écrire en cache coûte plus cher qu'une entrée


TARIFS_GROQ = {
    "openai/gpt-oss-20b": Tarif(entree=0.075, lecture_cache=0.0375, sortie=0.30),
    "openai/gpt-oss-120b": Tarif(entree=0.15, lecture_cache=0.075, sortie=0.60),
}

# Petit modèle -> petit modèle, gros modèle -> gros modèle : même rôle dans le système.
EQUIVALENT_ANTHROPIC = {
    "openai/gpt-oss-20b": "claude-haiku-5-5",
    "openai/gpt-oss-120b": "claude-sonnet-5-5",
}
TARIFS_ANTHROPIC = {
    "claude-haiku-5-5": Tarif(entree=0.10, lecture_cache=0.01, sortie=0.50, ecriture_cache=0.125),
    "claude-sonnet-5-5": Tarif(entree=2.00, lecture_cache=0.10, sortie=10.00, ecriture_cache=2.50),
}

M = 1_000_000


def cout_groq(modele: str, entree: int, caches: int, sortie: int) -> float | None:
    """entree = tous les tokens du prompt, dont `caches` lus en cache (Groq les facture moitié prix)."""
    tarif = TARIFS_GROQ.get(modele)
    if tarif is None:
        return None
    return ((entree - caches) * tarif.entree + caches * tarif.lecture_cache + sortie * tarif.sortie) / M


def cout_anthropic(modele_groq: str, entree: int, caches: int, sortie: int, avec_cache: bool) -> float | None:
    """Même appel facturé par le modèle Claude équivalent.

    Sans cache : tout le prompt au prix d'entrée.
    Avec cache (hypothèse) : ce que Groq a lu en cache serait une lecture de cache chez Anthropic,
    et le reste du prompt serait écrit en cache (5 min) pour l'appel suivant, au prix d'écriture.
    """
    tarif = TARIFS_ANTHROPIC.get(EQUIVALENT_ANTHROPIC.get(modele_groq, ""))
    if tarif is None:
        return None
    if not avec_cache:
        return (entree * tarif.entree + sortie * tarif.sortie) / M
    return ((entree - caches) * tarif.ecriture_cache + caches * tarif.lecture_cache + sortie * tarif.sortie) / M


# --- Bilan d'une exécution ---------------------------------------------------------------------


class LigneLLM(BaseModel):
    cle: str                       # agent (ou modèle)
    appels: int = 0                # appels réussis
    echecs: int = 0                # tentatives en erreur (429, 5xx, schéma refusé...)
    tokens_entree: int = 0
    tokens_caches: int = 0
    tokens_sortie: int = 0
    tokens_raisonnement: int = 0   # inclus dans tokens_sortie : le raisonnement se paie au prix de la sortie
    duree_ms: float = 0
    cout_groq: float = 0
    cout_anthropic: float = 0
    cout_anthropic_cache: float = 0

    @property
    def taux_cache(self) -> float:
        return self.tokens_caches / self.tokens_entree if self.tokens_entree else 0.0


class LigneOutil(BaseModel):
    outil: str
    appels: int = 0
    erreurs: int = 0               # exception, ou résultat {"erreur": ...} renvoyé au modèle
    duree_ms: float = 0
    caracteres: int = 0            # taille des résultats : ce qui entrera dans le contexte du LLM
    cout_apify: float = 0


class Bilan(BaseModel):
    execution_id: str
    duree_s: float
    par_agent: list[LigneLLM]
    par_outil: list[LigneOutil]
    total: LigneLLM
    cout_apify: float


def ajouter_appel(ligne: LigneLLM, span: dict) -> None:
    attributs = span["attributs"]
    if span["statut"] != "ok":
        ligne.echecs += 1
        return
    entree, caches, sortie = attributs["tokens_entree"], attributs["tokens_caches"], attributs["tokens_sortie"]
    modele = attributs["modele"]
    ligne.appels += 1
    ligne.tokens_entree += entree
    ligne.tokens_caches += caches
    ligne.tokens_sortie += sortie
    ligne.tokens_raisonnement += attributs.get("tokens_raisonnement", 0)
    ligne.duree_ms += span["duree_ms"]
    ligne.cout_groq += cout_groq(modele, entree, caches, sortie) or 0
    ligne.cout_anthropic += cout_anthropic(modele, entree, caches, sortie, avec_cache=False) or 0
    ligne.cout_anthropic_cache += cout_anthropic(modele, entree, caches, sortie, avec_cache=True) or 0


def faire_bilan(spans: list[dict]) -> Bilan:
    par_agent: dict[str, LigneLLM] = {}
    par_outil: dict[str, LigneOutil] = defaultdict(lambda: LigneOutil(outil=""))
    total = LigneLLM(cle="total")
    racine = next((s for s in spans if s["type"] == "execution"), None)

    for s in spans:
        if s["type"] == "llm":
            agent = s["attributs"].get("agent", s["nom"])
            ajouter_appel(par_agent.setdefault(agent, LigneLLM(cle=agent)), s)
            ajouter_appel(total, s)
        elif s["type"] == "outil":
            ligne = par_outil[s["nom"]]
            ligne.outil = s["nom"]
            ligne.appels += 1
            ligne.erreurs += int(s["statut"] != "ok" or s["attributs"].get("resultat") != "ok")
            ligne.duree_ms += s["duree_ms"]
            ligne.caracteres += s["attributs"].get("caracteres", 0)
            ligne.cout_apify += s["attributs"].get("cout_apify_usd") or 0

    return Bilan(
        execution_id=racine["nom"] if racine else "?",
        duree_s=round(racine["duree_ms"] / 1000, 1) if racine else 0,
        par_agent=sorted(par_agent.values(), key=lambda ligne: -ligne.cout_groq),
        par_outil=sorted(par_outil.values(), key=lambda ligne: ligne.outil),
        total=total,
        cout_apify=sum(ligne.cout_apify for ligne in par_outil.values()),
    )


def dollars(valeur: float) -> str:
    return f"{valeur:.4f} $" if valeur < 1 else f"{valeur:.2f} $"


def formater_bilan(bilan: Bilan) -> str:
    lignes = [
        f"### Exécution {bilan.execution_id} — {bilan.duree_s} s",
        "",
        "| Agent | Appels | Échecs | Entrée | dont cache | Sortie | dont raisonnement | Durée LLM | Groq | Claude | Claude + cache |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ligne in [*bilan.par_agent, bilan.total]:
        nom = f"**{ligne.cle}**" if ligne.cle == "total" else ligne.cle
        lignes.append(
            f"| {nom} | {ligne.appels} | {ligne.echecs} | {ligne.tokens_entree} | "
            f"{ligne.tokens_caches} ({ligne.taux_cache:.0%}) | {ligne.tokens_sortie} | {ligne.tokens_raisonnement} | "
            f"{ligne.duree_ms / 1000:.1f} s | {dollars(ligne.cout_groq)} | {dollars(ligne.cout_anthropic)} | "
            f"{dollars(ligne.cout_anthropic_cache)} |"
        )
    if bilan.par_outil:
        lignes += ["", "| Outil | Appels | Erreurs | Durée | Caractères renvoyés | Apify |", "|---|---:|---:|---:|---:|---:|"]
        for o in bilan.par_outil:
            lignes.append(
                f"| {o.outil} | {o.appels} | {o.erreurs} | {o.duree_ms / 1000:.1f} s | {o.caracteres} | "
                f"{dollars(o.cout_apify)} |"
            )
    return "\n".join(lignes)
