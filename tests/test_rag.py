import hashlib
import json
from datetime import date, datetime

import numpy as np
import pytest

from veille.agents.analyste import AnalyseMarque
from veille.agents.rapport import Constat, RapportVeille
from veille.agents.signaux import Signaux
from veille.rag.bm25 import BM25, tokeniser
from veille.rag.documents import (
    Morceau,
    charger_corpus,
    decouper_texte,
    morceaux_depuis_analyse,
)
from veille.rag.recherche import MoteurRecherche, fusion_rrf
from veille.rag.reponse import Affirmation, ReponseRAG, verifier_citations
from veille.storage.analyses import enregistrer_analyse


def faux_encodeur(textes: list[str]) -> np.ndarray:
    """Sac de mots haché : déterministe, sans modèle à télécharger."""
    vecteurs = np.zeros((len(textes), 256))
    for n, texte in enumerate(textes):
        for mot in tokeniser(texte):
            vecteurs[n, int(hashlib.md5(mot.encode()).hexdigest(), 16) % 256] += 1
    return vecteurs


def morceau(id_: str, texte: str, marque: str = "Typology") -> Morceau:
    return Morceau(id=id_, texte=texte, marque=marque, type="pub", source="meta", date=date(2026, 10, 23))


PUB = {
    "id": "123", "marque": "Typology", "date_debut": "2026-01-14T08:00:00Z", "duree_jours": 283, "active": True,
    "plateformes": ["FACEBOOK", "INSTAGRAM"], "format": "VIDEO", "textes": ["Coffret de Noël offert dès 60 €"],
    "lien": "https://typology.com/coffret?utm_source=meta", "appel_a_l_action": "Shop now",
}


def analyse(jour: int, duree: int = 283) -> AnalyseMarque:
    pub = {**PUB, "duree_jours": duree}
    return AnalyseMarque(
        marque="Typology", date=date(2026, 10, jour), horodatage=datetime(2026, 10, jour, 9, 0, 0), execution_id="t",
        observations=[
            json.dumps({"marque": "Typology", "nb_pubs": 1, "pubs": [pub]}),
            json.dumps({"url": "https://typology.com/coffret", "texte": "Un coffret de soins. " * 60}),
            json.dumps({"erreur": "TikTok indisponible"}),
            "pas du JSON",
        ],
        signaux=Signaux(nb_pubs={"meta": 1}, formats={"VIDEO": 1}, pub_la_plus_durable=None, sources_en_erreur=[]),
        rapport=RapportVeille(
            marque="Typology", produits_pousses=[Constat(affirmation="Le coffret de Noël est poussé.", sources=["meta"])],
            messages_et_promesses=[], offres=[], formats_et_plateformes=[], cible=[], donnees_manquantes=[],
        ),
    )


# --- Découpage ---

def test_texte_court_un_seul_morceau():
    assert decouper_texte("  Une   phrase\ncourte. ") == ["Une phrase courte."]


def test_texte_long_morceaux_bornes_avec_recouvrement_sans_mot_coupe():
    mots = [f"mot{i}" for i in range(400)]
    morceaux = decouper_texte(" ".join(mots), taille=200, recouvrement=50)

    assert len(morceaux) > 1
    assert all(len(m) <= 200 for m in morceaux)
    assert all(set(m.split()) <= set(mots) for m in morceaux)            # aucun mot coupé
    assert morceaux[0].split()[-1] in morceaux[1].split()                 # recouvrement
    assert morceaux[-1].split()[-1] == "mot399"                           # rien de perdu à la fin


# --- Morceaux depuis les analyses ---

def test_une_analyse_donne_pub_pages_et_constat():
    morceaux = morceaux_depuis_analyse(analyse(23))
    types = [m.type for m in morceaux]

    assert types.count("pub") == 1 and types.count("constat") == 1 and types.count("page") > 1
    pub = next(m for m in morceaux if m.type == "pub")
    assert pub.id == "pub:meta:123"
    assert pub.lien == "https://typology.com/coffret"                    # paramètres de suivi retirés
    assert "Coffret de Noël" in pub.texte and "283 jours" in pub.texte


def test_une_pub_revue_a_chaque_veille_reste_un_seul_morceau(tmp_path):
    enregistrer_analyse(analyse(22, duree=282), tmp_path)
    enregistrer_analyse(analyse(23, duree=283), tmp_path)
    (tmp_path / "ancien.json").write_text('{"marque": "X"}', encoding="utf-8")

    morceaux, ignores = charger_corpus([tmp_path])

    pubs = [m for m in morceaux if m.type == "pub"]
    assert len(pubs) == 1
    assert pubs[0].vu_le == [date(2026, 10, 22), date(2026, 10, 23)]
    assert "283 jours" in pubs[0].texte                                  # la version la plus récente
    assert ignores == 1


# --- BM25 ---

def test_tokeniser_sans_accents_ni_mots_vides():
    assert tokeniser("La crème hydratante de Noël") == ["creme", "hydratante", "noel"]


def test_bm25_classe_le_document_qui_contient_le_mot_rare():
    bm25 = BM25(["crème visage", "crème corps", "sérum vitamine C"])
    scores = bm25.scores("sérum")
    assert scores[2] > 0 and scores[0] == scores[1] == 0
    assert bm25.idf["serum"] > bm25.idf["creme"]                         # mot rare = plus discriminant


# --- Fusion et recherche ---

def test_rrf_favorise_le_document_bien_classe_partout():
    scores = fusion_rrf([[1, 2, 3], [2, 3, 1]])
    assert max(scores, key=scores.get) == 2


def test_filtre_par_marque():
    moteur = MoteurRecherche(
        [morceau("a", "coffret Noël", "Typology"), morceau("b", "coffret Noël", "Respire")], faux_encodeur
    )
    resultats = moteur.rechercher("coffret", marque="respire", mode="hybride")
    assert [r.morceau.id for r in resultats] == ["b"]


def test_le_reranking_change_le_premier_resultat():
    morceaux = [
        morceau("d1", "crème hydratante crème hydratante visage"),
        morceau("d2", "sérum hydratante"),
        morceau("d3", "parfum boisé"),
    ]
    reranker = lambda question, textes: [1.0 if "sérum" in t else 0.0 for t in textes]
    moteur = MoteurRecherche(morceaux, faux_encodeur, reranker)

    hybride = moteur.rechercher("crème hydratante", mode="hybride")
    rerank = moteur.rechercher("crème hydratante", mode="rerank")

    assert hybride[0].morceau.id == "d1"
    assert rerank[0].morceau.id == "d2"
    assert rerank[0].rangs["hybride"] == 2                               # remonté de la 2e à la 1re place


def test_mode_rerank_sans_reranker_refuse():
    moteur = MoteurRecherche([morceau("a", "coffret")], faux_encodeur)
    with pytest.raises(ValueError):
        moteur.rechercher("coffret", mode="rerank")


# --- Citations ---

def test_citations_inventees_retirees():
    etiquettes = {"M1": morceau("a", "coffret"), "M2": morceau("b", "sérum")}
    reponse = ReponseRAG(information_absente=False, affirmations=[
        Affirmation(texte="Typology pousse un coffret.", citations=["M1", "[M9]"]),
        Affirmation(texte="Phrase inventée.", citations=["M7"]),
        Affirmation(texte="Phrase sans citation.", citations=[]),
    ])

    gardees, retirees = verifier_citations(reponse, etiquettes)

    assert [a.texte for a in gardees] == ["Typology pousse un coffret."]
    assert [m.id for m in gardees[0].sources] == ["a"]
    assert retirees == 2
