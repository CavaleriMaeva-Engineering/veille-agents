import asyncio
from collections.abc import Callable
from typing import Any


async def executer_en_parallele(appels: list[Callable[[], Any]], max_simultanes: int = 3) -> list[Any]:
    semaphore = asyncio.Semaphore(max_simultanes)

    async def executer(appel: Callable[[], Any]) -> Any:
        async with semaphore:
            return await asyncio.to_thread(appel)

    return await asyncio.gather(*(executer(appel) for appel in appels), return_exceptions=True)