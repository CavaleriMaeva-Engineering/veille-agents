from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from veille.agents.analyste import AnalyseMarque
from veille.agents.synthese import SyntheseVeille

STYLES = getSampleStyleSheet()
SECTIONS = [
    ("Produits poussés", "produits_pousses"),
    ("Messages et promesses", "messages_et_promesses"),
    ("Offres", "offres"),
    ("Formats et plateformes", "formats_et_plateformes"),
    ("Cible", "cible"),
]
# caractères que les polices standard du PDF ne savent pas afficher
REMPLACEMENTS = {"\u2011": "-", "\u202f": " ", "\u00a0": " "}


def nettoyer(texte: str) -> str:
    for avant, apres in REMPLACEMENTS.items():
        texte = texte.replace(avant, apres)
    return escape(texte)


def paragraphe(texte: str, style: str = "BodyText") -> Paragraph:
    return Paragraph(nettoyer(texte), STYLES[style])


def puces(textes: list[str]) -> list[Paragraph]:
    return [Paragraph(nettoyer(t), STYLES["BodyText"], bulletText="•") for t in textes]


def tableau_chiffres(synthese: SyntheseVeille) -> Table:
    durables = {d.marque: d.pub.duree_jours for d in synthese.signaux.classement_pubs_durables}
    lignes = [["Marque", "Pubs actives", "Pub la plus durable"]] + [
        [marque, str(nb), f"{durables[marque]} jours" if marque in durables else "—"]
        for marque, nb in synthese.signaux.nb_pubs_par_marque.items()
    ]
    tableau = Table(lignes, hAlign="LEFT")
    tableau.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    return tableau


def page_marque(analyse: AnalyseMarque) -> list:
    elements = [paragraphe(analyse.marque, "Heading1")]
    if not analyse.signaux.nb_pubs:
        elements.append(paragraphe("Aucune pub active trouvée : rien à conclure sur cette marque."))
    for titre, champ in SECTIONS:
        constats = getattr(analyse.rapport, champ)
        if constats:
            elements.append(paragraphe(titre, "Heading2"))
            elements += puces([f"{c.affirmation} [{', '.join(c.sources)}]" for c in constats])
    if analyse.rapport.donnees_manquantes:
        elements.append(paragraphe("Données manquantes", "Heading2"))
        elements += puces(analyse.rapport.donnees_manquantes)
    return elements


def generer_pdf(synthese: SyntheseVeille, analyses: list[AnalyseMarque], chemin: Path) -> Path:
    s = synthese.synthese
    couverture = [f"Marques analysées : {', '.join(synthese.marques_analysees) or 'aucune'}"]
    if synthese.signaux.marques_sans_pub:
        couverture.append(f"Sans pub active trouvée : {', '.join(synthese.signaux.marques_sans_pub)}")
    couverture += [f"{marque} : non analysée ({cause})" for marque, cause in synthese.echecs.items()]

    elements = [
        paragraphe("Veille publicitaire concurrentielle", "Title"),
        paragraphe(f"Rapport du {synthese.horodatage:%d/%m/%Y à %H:%M} · exécution {synthese.execution_id}"),
        Spacer(1, 0.4 * cm),
        paragraphe("Chiffres clés (calculés par le code)", "Heading2"),
        tableau_chiffres(synthese),
        paragraphe("Pubs les plus durables du marché", "Heading2"),
        *puces([
            f"{d.marque} : {d.pub.duree_jours} jours ({d.pub.source}). « {d.pub.texte or ''} »"
            for d in synthese.signaux.classement_pubs_durables
        ]),
        paragraphe("Tendances communes", "Heading2"), *puces(s.tendances_communes),
        paragraphe("Positionnements", "Heading2"), *puces([f"{p.marque} : {p.positionnement}" for p in s.positionnements]),
        paragraphe("Différences notables", "Heading2"), *puces(s.differences_notables),
        paragraphe("Couverture de la veille", "Heading2"), *puces(couverture),
        paragraphe("Limites signalées par l'analyse", "Heading2"), *puces(s.limites),
    ]
    for analyse in analyses:
        if analyse.signaux.nb_pubs:   # les marques sans pub sont déjà dans la couverture
            elements += [PageBreak(), *page_marque(analyse)]

    chemin.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(chemin), pagesize=A4, title="Veille publicitaire").build(elements)
    return chemin