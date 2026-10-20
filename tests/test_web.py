import httpx

from veille.tools.web import OUTIL_LIRE_PAGE_WEB, lire_page_web


def test_page_introuvable(monkeypatch):
    # Préparer : un faux Internet où toute page renvoie 404
    def faux_get(url, **kwargs):
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", faux_get)

    # Agir
    resultat = lire_page_web("https://exemple.test/absente")

    # Vérifier
    assert "erreur" in resultat
    assert "404" in resultat["erreur"]


def test_adresse_mal_formee():
    # Préparer : rien. La fonction doit s'arrêter avant tout appel réseau,
    # dès la vérification du « https:// »

    # Agir
    resultat = lire_page_web("http://exemple.test")

    # Vérifier
    assert "erreur" in resultat


def test_page_nettoyee_et_coupee(monkeypatch):
    # Préparer : un faux Internet qui renvoie une page avec un script de pub
    def faux_get(url, **kwargs):
        html = (
            "<html><script>alert('pub')</script><p>Bonjour les concurrents</p></html>"
        )
        return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", faux_get)

    # Agir : on demande au plus 7 caractères
    resultat = lire_page_web("https://exemple.test", max_caracteres=7)

    # Vérifier
    assert "alert" not in resultat["texte"]  # le script a bien été supprimé
    assert len(resultat["texte"]) <= 7  # le texte a bien été coupé


def test_description_outil():
    fonction = OUTIL_LIRE_PAGE_WEB["function"]

    assert fonction["name"] == "lire_page_web"
    assert "url" in fonction["parameters"]["required"]
