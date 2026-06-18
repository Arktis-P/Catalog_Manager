from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from app.services.db_write_queue import DbWriteQueue


def test_db_write_queue_serializes_commits_in_fifo_order() -> None:
    queue = DbWriteQueue()
    order: list[str] = []
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        barrier.wait()
        ticket = queue.acquire(name)
        order.append(f"start:{name}")
        time.sleep(0.05)
        order.append(f"end:{name}")
        queue.release(name, ticket)

    threads = [threading.Thread(target=worker, args=(f"job-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert order.index("start:job-0") < order.index("end:job-0")
    assert order.index("end:job-0") < order.index("start:job-1")
    assert order.index("start:job-1") < order.index("end:job-1")


def test_commit_db_session_rolls_back_on_failure() -> None:
    queue = DbWriteQueue()
    db = MagicMock()
    db.commit.side_effect = RuntimeError("boom")

    try:
        queue.commit_session(db, owner="job:test")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected commit failure")

    db.rollback.assert_called_once()
