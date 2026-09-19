"""Cancellation-safe bridging between a background generation task and an SSE stream.

Background
----------
Several routes run generation in a detached `asyncio.create_task(...)` and
drain its tokens through a queue while yielding SSE frames. When the client
aborts (the frontend's AbortController, a closed tab, a dropped connection),
Starlette cancels the task running the response generator — but a task created
with `create_task` is NOT a child of that task, so it keeps running. The result
is that Ollama carries on generating a reply nobody will ever read, burning CPU
and, on a small local box, blocking the next request.

`drain_task_queue` guarantees the background task is cancelled whenever the
consumer goes away, by cancelling it in a `finally` block that runs on
GeneratorExit / CancelledError as well as on normal completion.
"""

import asyncio
from typing import Any, AsyncIterator


async def drain_task_queue(
    task: asyncio.Task,
    queue: asyncio.Queue,
    poll_interval: float = 0.1,
) -> AsyncIterator[Any]:
    """Yield items from `queue` until `task` finishes, cancelling `task` if the
    consumer stops early.

    The caller is responsible for awaiting `task` afterwards to collect its
    result (it will already be done by then).
    """
    try:
        while not task.done():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=poll_interval)
            except asyncio.TimeoutError:
                continue
        # Flush anything produced between the last poll and the task finishing.
        while not queue.empty():
            yield queue.get_nowait()
    finally:
        # Runs on normal exit, on GeneratorExit (consumer closed the stream)
        # and on CancelledError (client disconnected). Stops server-side
        # generation instead of letting it run to completion unseen.
        if not task.done():
            task.cancel()
