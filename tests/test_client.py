from veille.llm.client import calculer_delai


def test_delai_double():
    assert calculer_delai(1, jitter=0) == 1
    assert calculer_delai(2, jitter=0) == 2
    assert calculer_delai(3, jitter=0) == 4


def test_delai_plafonne():
    assert calculer_delai(20, jitter=0) == 30
    assert 30 <= calculer_delai(7, plafond=30, jitter=1) <= 30 + 1

    assert calculer_delai(5, plafond=10, jitter=0) == 10
