import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from veille.reseau import appeler_avec_tentatives
from veille.tools.base import decrire_outil


class ArgsLirePageWeb(BaseModel):
    url: str = Field(description="Adresse complète de la page, commençant par https://")


OUTIL_LIRE_PAGE_WEB = decrire_outil(
    nom="lire_page_web",
    description=(
        "Lit le texte d'une page web publique d'une marque concurrente : page d'accueil, "
        "page produit, page de prix ou de promotion. À utiliser pour vérifier un prix, une offre "
        "ou un nouveau produit repéré dans une publicité. Renvoie le texte visible de la page, "
        "nettoyé et limité à quelques milliers de caractères. Ne fonctionne pas sur les pages "
        "qui demandent une connexion ni sur les réseaux sociaux : pour les publicités, "
        "utilise plutôt chercher_pubs_meta ou chercher_pubs_tiktok."
    ),
    args=ArgsLirePageWeb,
)


def lire_page_web(url: str, max_caracteres: int = 5000) -> dict:
    if not url.startswith("https://"):
        return {
            "erreur": "L'adresse doit commencer par https://. Corrige-la et réessaie."
        }

    def telecharger():
        reponse = httpx.get(
            url,
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "veille-agents/0.1 (student project)"},
        )
        reponse.raise_for_status()
        html = reponse.text
        return html

    try:
        html = appeler_avec_tentatives(telecharger, max_tentatives=3)
    except httpx.HTTPStatusError as erreur:
        code = erreur.response.status_code
        if code == 404:
            return {
                "erreur": "Page introuvable (404). Vérifie l'adresse, ou essaie la page d'accueil de la marque."
            }
        if code == 403:
            return {
                "erreur": "Le site refuse l'accès automatique (403). N'insiste pas, utilise une autre source."
            }
        return {
            "erreur": f"Le site a répondu avec une erreur {code}. Réessaie plus tard ou utilise une autre source."
        }
    except httpx.TimeoutException:
        return {
            "erreur": "Le site n'a pas répondu à temps, même après plusieurs essais. Passe à une autre source."
        }
    except httpx.HTTPError:
        return {
            "erreur": "Impossible de joindre ce site. Vérifie l'adresse, ou utilise une autre source."
        }

    soupe = BeautifulSoup(html, "html.parser")
    for balise in soupe(["script", "style", "nav", "footer", "header"]):
        balise.decompose()
    texte = soupe.get_text(separator=" ", strip=True)
    return {"url": url, "texte": texte[:max_caracteres]}
