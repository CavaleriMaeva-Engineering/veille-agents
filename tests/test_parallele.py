import asyncio
import time
from functools import partial

from veille.parallele import executer_en_parallele


def tache_lente(numero: int, duree: float = 0.2) -> int:
    time.sleep(duree)
    return numero


def tache_qui_plante() -> None:
    raise ValueError("panne")


def test_plus_rapide_que_sequentiel():
    appels = [partial(tache_lente, i) for i in range(6)]

    debut = time.perf_counter()
    resultats = asyncio.run(executer_en_parallele(appels, max_simultanes=3))
    duree = time.perf_counter() - debut

    assert resultats == [0, 1, 2, 3, 4, 5]   # l'ordre des appels est conservé
    assert 0.35 < duree < 0.8                # 2 vagues de 3 × 0,2 s ≈ 0,4 s, au lieu de 1,2 s en séquentiel


def test_une_panne_ne_perd_pas_les_autres_resultats():
    appels = [partial(tache_lente, 1, 0.01), tache_qui_plante, partial(tache_lente, 3, 0.01)]

    resultats = asyncio.run(executer_en_parallele(appels))

    assert resultats[0] == 1
    assert isinstance(resultats[1], ValueError)
    assert resultats[2] == 3