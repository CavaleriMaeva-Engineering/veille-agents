from veille.tools.web import lire_page_web

resultat = lire_page_web("https://www.typology.com")
print(resultat.get("erreur") or resultat["texte"][:500])

print()

resultat = lire_page_web("https://www.typology.com/page-qui-nexiste-pas")
print(resultat)
