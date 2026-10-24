import json

from veille.evals.juge import Paire
from veille.evals.rag import Annotation, CasRAG
from veille.evals.verification import (
    dernier_releve,
    formater,
    verifier_jeu,
    verifier_juge,
    verifier_recherche,
    verifier_tout,
)


def cas(identifiant, type_="normal", attendu="reponse"):
    return CasRAG(id=identifiant, question="q ?", type=type_, attendu=attendu)


def annotation(*pertinents, auteur="maeva"):
    return Annotation(pertinents=list(pertinents), annote_par=auteur, annote_le="2026-10-24")


def jeu_sain():
    types = ["normal"] * 16 + ["limite"] * 5 + ["adverse"] * 5
    liste = [cas(f"r{i:02d}", t, "abstention" if t == "adverse" else "reponse") for i, t in enumerate(types, 1)]
    annotations = {c.id: annotation() if c.attendu == "abstention" else annotation("m1") for c in liste}
    return liste, annotations


def echecs(controles):
    return {c.nom for c in controles if not c.ok}


# --- Le jeu d'évals ----------------------------------------------------------------------------------

def test_un_jeu_sain_passe():
    assert echecs(verifier_jeu(*jeu_sain())) == set()


def test_trop_peu_de_cas():
    liste, annotations = jeu_sain()
    assert "nombre de cas" in echecs(verifier_jeu(liste[:10], annotations))


def test_un_cas_sans_annotation_et_une_annotation_orpheline():
    liste, annotations = jeu_sain()
    del annotations["r01"]
    annotations["r99"] = annotation("m1")

    manques = echecs(verifier_jeu(liste, annotations))

    assert {"tous les cas sont annotés", "aucune annotation orpheline"} <= manques


def test_un_type_de_cas_manquant():
    liste, annotations = jeu_sain()
    sans_adverse = [c for c in liste if c.type != "adverse"] + [cas("r90"), cas("r91"), cas("r92"), cas("r93")]
    for c in sans_adverse:
        annotations.setdefault(c.id, annotation("m1"))
    assert "trois types de cas" in echecs(verifier_jeu(sans_adverse, annotations))


def test_une_abstention_attendue_alors_qu_un_extrait_est_pertinent_est_incoherente():
    liste, annotations = jeu_sain()
    annotations["r22"] = annotation("m1")   # r22 est un cas adverse : on s'abstient
    assert "abstention cohérente" in echecs(verifier_jeu(liste, annotations))


def test_une_annotation_sans_auteur():
    liste, annotations = jeu_sain()
    annotations["r01"] = annotation("m1", auteur=" ")
    assert "annotations signées" in echecs(verifier_jeu(liste, annotations))


# --- La recherche ------------------------------------------------------------------------------------

def releve(rerank=(0.75, 0.98), hybride=(0.5, 0.7)):
    return [
        {"cas": "r01", "mode": "rerank", "precision": 0.6, "rappel": rerank[0], "rr": rerank[1]},
        {"cas": "r01", "mode": "hybride", "precision": 0.4, "rappel": hybride[0], "rr": hybride[1]},
    ]


def test_un_bon_releve_de_recherche_passe():
    assert echecs(verifier_recherche(releve())) == set()


def test_un_rerank_qui_se_degrade_casse_la_ci():
    assert "rappel@5 du reranking" in echecs(verifier_recherche(releve(rerank=(0.40, 0.98))))
    assert "MRR du reranking" in echecs(verifier_recherche(releve(rerank=(0.75, 0.60))))


def test_un_rerank_qui_ne_bat_plus_l_hybride_est_signale():
    assert "le reranking apporte quelque chose" in echecs(
        verifier_recherche(releve(rerank=(0.70, 0.98), hybride=(0.72, 0.7)))
    )


def test_un_releve_sans_les_modes_attendus_echoue_au_lieu_de_planter():
    sans_rerank = [x for x in releve() if x["mode"] != "rerank"]
    assert echecs(verifier_recherche(sans_rerank)) == {"relevé de recherche complet"}


# --- Le juge -----------------------------------------------------------------------------------------

def paires(accord_sur: int, total: int = 100, stables: bool = True):
    """`accord_sur` paires où le juge est d'accord avec l'humain, les autres en désaccord (moitié oui, moitié non)."""
    resultat = []
    for i in range(total):
        humain = i % 2 == 0
        juge = humain if i < accord_sur else not humain
        resultat.append(Paire(cas="r01", morceau=f"m{i}", longueur=100 + i, humain=humain,
                              endroit=juge, envers=juge if stables else (not juge)))
    return resultat


def test_un_juge_qui_accorde_passe():
    assert echecs(verifier_juge(paires(98))) == set()


def test_un_juge_qui_decroche_casse_la_ci():
    assert "kappa du juge avec l'humain" in echecs(verifier_juge(paires(70)))


def test_un_juge_sensible_a_l_ordre_casse_la_ci():
    instables = paires(100)
    for p in instables[:30]:
        p.envers = not p.endroit
    assert "stabilité du juge à l'inversion de l'ordre" in echecs(verifier_juge(instables))


# --- Les fichiers ------------------------------------------------------------------------------------

def test_le_dernier_releve_est_le_plus_recent_par_son_horodatage(tmp_path):
    for nom in ["2026-10-23T19-09_details.json", "2026-10-24T08-00_details.json", "2026-10-22T10-00_details.json"]:
        (tmp_path / nom).write_text("[]")
    assert dernier_releve(tmp_path, "*_details.json").name == "2026-10-24T08-00_details.json"
    assert dernier_releve(tmp_path, "*_juge_paires.json") is None


def test_un_dossier_sans_releves_echoue_proprement(tmp_path):
    (tmp_path / "resultats").mkdir()
    (tmp_path / "cas_rag.yaml").write_text(
        "\n".join(f"- {{id: r{i:02d}, question: q, type: {t}}}" for i, t in
                  enumerate(["normal"] * 18 + ["limite"] * 4 + ["adverse"] * 4, 1))
    )
    (tmp_path / "annotations_rag.json").write_text(json.dumps({}))

    manques = echecs(verifier_tout(tmp_path))

    assert {"relevé de recherche présent", "relevé du juge présent", "tous les cas sont annotés"} <= manques


def test_les_evals_commitees_du_projet_passent_les_controles():
    """Ce test lit les vrais fichiers du dépôt : c'est ce que la CI exécute aussi via scripts/verifier_evals.py."""
    controles = verifier_tout()
    assert echecs(controles) == set(), formater(controles)


def test_le_rapport_dit_ok_ou_echec():
    texte = formater(verifier_recherche(releve(rerank=(0.40, 0.99), hybride=(0.30, 0.70))))
    assert "ÉCHEC" in texte and "OK" in texte
