"""Banc de coûts (PJ15) : rejoue la dernière veille SANS Apify sous plusieurs réglages, et compare.

Les outils sont remplacés par leurs résultats enregistrés dans sorties/ : seuls les appels LLM sont réels.
Chaque réglage produit une trace (traces/*.jsonl) ; le script écrit le tableau avant/après dans docs/couts.md.

Usage : uv run python scripts/mesurer_couts.py [--reglages avant apres] [--marques 5]
"""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from veille.agents.analyste import collecter_marque, rediger_analyse
from veille.agents.rapport import SECTIONS_CONSTATS
from veille.couts import (
    DATE_TARIFS,
    SOURCES_TARIFS,
    Bilan,
    dollars,
    faire_bilan,
    formater_bilan,
)
from veille.garde_fous import normaliser_url, verifier_ancrage
from veille.llm.client import creer_client_groq
from veille.settings import Config, ReglageLLM, Secrets, charger_config
from veille.tools.meta import OUTIL_CHERCHER_PUBS_META, ArgsChercherPubsMeta
from veille.tools.registre import Outil
from veille.tools.web import OUTIL_LIRE_PAGE_WEB, ArgsLirePageWeb
from veille.traces import lire_spans, span, tracer

logging.basicConfig(level=logging.WARNING, format="%(message)s")

# "avant" = le système tel qu'il était avant PJ15 : tout sur le modèle par défaut, effort du modèle par défaut.
# "apres" = les réglages par étape de config/marche.yaml.
# "tout_120b" = contre-factuel : et si on mettait le gros modèle partout ? (justifie le routage)
REGLAGES = {
    "avant": {},
    "apres": None,
    "tout_120b": {
        "collecteur": ReglageLLM(modele="openai/gpt-oss-120b"),
        "redacteur": ReglageLLM(modele="openai/gpt-oss-120b"),
    },
}


def dernieres_analyses(dossier: Path = Path("sorties")) -> dict[str, dict]:
    """La dernière analyse enregistrée de chaque marque (hors synthèses et archives)."""
    dernieres: dict[str, dict] = {}
    for chemin in sorted(dossier.glob("*_veille-*.json")):
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        if donnees.get("observations") is not None:
            dernieres[donnees["marque"]] = donnees   # tri par nom = tri par date : la plus récente gagne
    return dernieres


def outils_rejoues(observations: list[str]) -> dict[str, Outil]:
    """Les outils de la collecte, mais qui renvoient ce qu'ils avaient renvoyé ce jour-là."""
    resultats = [json.loads(o) for o in observations]
    pubs = next((r for r in resultats if "nb_pubs" in r), {"erreur": "Bibliothèque Meta indisponible."})
    pages = {normaliser_url(r["url"]): r for r in resultats if "url" in r and "texte" in r}

    def lire_page_web(url: str) -> dict:
        return pages.get(normaliser_url(url)) or {
            "erreur": "Page introuvable (404). Vérifie l'adresse, ou essaie la page d'accueil de la marque."
        }

    return {
        "chercher_pubs_meta": Outil(OUTIL_CHERCHER_PUBS_META, ArgsChercherPubsMeta, lambda **_: dict(pubs)),
        "lire_page_web": Outil(OUTIL_LIRE_PAGE_WEB, ArgsLirePageWeb, lire_page_web),
    }


def mesurer(nom: str, config: Config, analyses: dict[str, dict], client) -> tuple[Path, list[dict]]:
    if REGLAGES[nom] is not None:
        config = config.model_copy(update={"etapes": REGLAGES[nom]})
    modele_c, effort_c = config.reglage("collecteur")
    modele_r, _ = config.reglage("redacteur")
    print(f"\n== Réglage « {nom} » : collecteur {modele_c} (effort {effort_c or 'défaut'}), rédacteur {modele_r}")

    qualite = []
    horodatage = datetime.now().strftime("%Y-%m-%dT%H-%M")
    with tracer(f"couts-{nom}-{horodatage}") as trace:
        for marque in config.marques:
            reference = analyses.get(marque.nom)
            if reference is None:
                continue
            id_marque = f"couts-{nom}-{marque.nom.lower().replace(' ', '-')}"
            try:
                with span("etape", "marque", marque=marque.nom):
                    with span("etape", "collecte", marque=marque.nom):
                        collecte = collecter_marque(
                            client, None, modele_c, marque, id_marque, outils_actifs=config.outils_actifs,
                            effort_raisonnement=effort_c, outils=outils_rejoues(reference["observations"]),
                        )
                    with span("etape", "redaction", marque=marque.nom):
                        rapport = rediger_analyse(client, modele_r, marque.nom, collecte, id_marque)
                    rapport, retires = verifier_ancrage(rapport, collecte.observations, collecte.signaux)
            except Exception as erreur:  # noqa: BLE001 — un quota épuisé sur une marque ne doit pas tout perdre
                print(f"   {marque.nom:13} ÉCHEC : {erreur!r}"[:200])
                qualite.append({"marque": marque.nom, "echec": repr(erreur)[:120]})
                continue
            ligne = {
                "marque": marque.nom,
                "outils": collecte.trajectoire.appels if collecte.trajectoire else [],
                "pubs": sum(collecte.signaux.nb_pubs.values()),   # nb_pubs = {source: nombre}
                "pubs_reference": sum(reference["signaux"]["nb_pubs"].values()),
                "constats": sum(len(getattr(rapport, s)) for s in SECTIONS_CONSTATS),
                "chiffres_retires": len(retires),
            }
            qualite.append(ligne)
            print(f"   {marque.nom:13} outils {ligne['outils']}  pubs {ligne['pubs']}/{ligne['pubs_reference']}  "
                  f"constats {ligne['constats']}  retirés à l'ancrage {ligne['chiffres_retires']}")
    trace.chemin.with_suffix(".qualite.json").write_text(json.dumps(qualite, ensure_ascii=False, indent=1), encoding="utf-8")
    return trace.chemin, qualite


def cout_collecte(bilan: Bilan) -> float:
    return next((ligne.cout_groq for ligne in bilan.par_agent if ligne.cle == "collecteur"), 0.0)


def tableau_comparatif(resultats: dict[str, tuple[Bilan, list[dict]]]) -> str:
    noms = list(resultats)
    entetes = "| | " + " | ".join(noms) + " |"
    lignes = [entetes, "|---|" + "---:|" * len(noms)]

    def rang(titre, f):
        lignes.append(f"| {titre} | " + " | ".join(f(*resultats[n]) for n in noms) + " |")

    def par_marque(bilan, qualite):
        reussies = max(sum("echec" not in q for q in qualite), 1)
        return reussies

    rang("Marques traitées", lambda b, q: f"{sum('echec' not in x for x in q)}/{len(q)}")
    rang("Appels LLM (échecs)", lambda b, q: f"{b.total.appels} ({b.total.echecs})")
    rang("Tokens d'entrée", lambda b, q: f"{b.total.tokens_entree}")
    rang("dont lus en cache", lambda b, q: f"{b.total.tokens_caches} ({b.total.taux_cache:.0%})")
    rang("Tokens de sortie", lambda b, q: f"{b.total.tokens_sortie}")
    rang("dont raisonnement", lambda b, q: f"{b.total.tokens_raisonnement}")
    rang("Temps passé dans le LLM", lambda b, q: f"{b.total.duree_ms / 1000:.1f} s")
    rang("Coût Groq par marque", lambda b, q: dollars(b.total.cout_groq / par_marque(b, q)))
    rang("Coût Claude par marque (sans cache)", lambda b, q: dollars(b.total.cout_anthropic / par_marque(b, q)))
    rang("Coût Claude par marque (avec cache)", lambda b, q: dollars(b.total.cout_anthropic_cache / par_marque(b, q)))
    rang("Coût Groq par marque si rien n'a changé (rapport repris)",
         lambda b, q: dollars(cout_collecte(b) / par_marque(b, q)))
    rang("Pubs Meta retrouvées", lambda b, q: f"{sum(x.get('pubs', 0) for x in q)}/{sum(x.get('pubs_reference', 0) for x in q)}")
    rang("Constats rédigés", lambda b, q: f"{sum(x.get('constats', 0) for x in q)}")
    rang("Chiffres retirés à l'ancrage", lambda b, q: f"{sum(x.get('chiffres_retires', 0) for x in q)}")
    return "\n".join(lignes)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesurer le coût d'une veille sous plusieurs réglages")
    parser.add_argument("--reglages", nargs="+", default=["avant", "apres"], choices=list(REGLAGES))
    parser.add_argument("--marques", type=int, default=5, help="nombre de marques rejouées")
    args = parser.parse_args()

    config = charger_config()
    config = config.model_copy(update={"marques": config.marques[: args.marques]})
    analyses = dernieres_analyses()
    client = creer_client_groq(Secrets())

    resultats = {}
    for nom in args.reglages:
        chemin, qualite = mesurer(nom, config, analyses, client)
        resultats[nom] = (faire_bilan(lire_spans(chemin)), qualite)
        print(formater_bilan(resultats[nom][0]))

    morceaux = [
        "# Coûts d'une veille : avant / après PJ15",
        "",
        (
            f"Mesuré le {datetime.now():%Y-%m-%d %H:%M} sur {args.marques} marques, en rejouant les données de la "
            "dernière veille (outils rejoués, appels LLM réels). Une seule mesure par réglage : à lire comme un "
            "ordre de grandeur, pas comme une moyenne."
        ),
        "",
        tableau_comparatif(resultats),
        "",
        f"Tarifs au {DATE_TARIFS} (dollars par million de tokens) :",
        *[f"- {s}" for s in SOURCES_TARIFS],
        (
            "- Claude = mêmes nombres de tokens facturés par l'équivalent (gpt-oss-20b → Haiku 5.5, "
            "gpt-oss-120b → Sonnet 5.5). « Avec cache » : ce que Groq a lu en cache serait lu en cache, "
            "le reste écrit en cache."
        ),
        "",
        "## Détail par réglage",
    ]
    for nom, (bilan, _) in resultats.items():
        morceaux += ["", f"#### {nom}", "", formater_bilan(bilan)]
    sortie = Path("docs/couts.md")
    sortie.parent.mkdir(exist_ok=True)
    sortie.write_text("\n".join(morceaux) + "\n", encoding="utf-8")
    print(f"\nTableau écrit dans {sortie}")


if __name__ == "__main__":
    main()
