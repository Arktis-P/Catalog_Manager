from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

_local = threading.local()


class DbWriteQueue:
    """FIFO queue so only one writer commits to SQLite at a time."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._next_ticket = 0
        self._holder: str | None = None
        self._holder_ticket: int | None = None
        self._waiters: list[tuple[int, str]] = []

    def acquire(self, owner: str) -> int:
        with self._cond:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._waiters.append((ticket, owner))

            while True:
                if self._holder is None and self._waiters and self._waiters[0][0] == ticket:
                    self._waiters.pop(0)
                    self._holder = owner
                    self._holder_ticket = ticket
                    return ticket
                self._cond.wait()

    def release(self, owner: str, ticket: int) -> None:
        with self._cond:
            if self._holder != owner or self._holder_ticket != ticket:
                raise RuntimeError(f"DbWriteQueue release by non-holder: {owner}")
            self._holder = None
            self._holder_ticket = None
            self._cond.notify_all()

    def commit_session(self, db: Session, *, owner: str) -> None:
        ticket = self.acquire(owner)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            self.release(owner, ticket)


db_write_queue = DbWriteQueue()


def get_write_owner() -> str:
    return getattr(_local, "owner", f"thread:{threading.get_ident()}")


@contextmanager
def job_write_context(job_id: str) -> Generator[None, None, None]:
    previous = getattr(_local, "owner", None)
    _local.owner = f"job:{job_id}"
    try:
        yield
    finally:
        if previous is None:
            if hasattr(_local, "owner"):
                delattr(_local, "owner")
        else:
            _local.owner = previous


def commit_db_session(db: Session, *, owner: str | None = None) -> None:
    db_write_queue.commit_session(db, owner=owner or get_write_owner())
