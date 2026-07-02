import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..core.logger import logger

_queue: asyncio.Queue = asyncio.Queue()
_processing = False


@dataclass
class IndexingJob:
    run: Callable[[], Awaitable[None]]


def enqueue_indexing_job(job: IndexingJob):
    _queue.put_nowait(job)
    asyncio.create_task(_process_queue())


async def _process_queue():
    global _processing
    if _processing:
        return
    _processing = True
    try:
        while not _queue.empty():
            job = await _queue.get()
            try:
                await job.run()
            except Exception as err:
                logger.error("indexingQueue job failed", {"error": str(err)})
    finally:
        _processing = False
