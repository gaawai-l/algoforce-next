"""Persistent work coordination; calculation stays pure and provider-independent."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Thread

from .calculation import calculate
from .market import Batch, Stream
from .repository import LeaseLost, Repository
from .sources import FetchError, fetch_market

logger = logging.getLogger("wheelhouse.worker")


class Runtime:
    def __init__(
        self, repository: Repository, *, fetch: Callable[[Stream, datetime], Batch] = fetch_market
    ) -> None:
        self.repository = repository
        self.fetch = fetch
        self.stopping = Event()
        self.thread: Thread | None = None

    def run_once(self, *, now: datetime | None = None) -> bool:
        # Fixed time is useful for replay/recovery verification; live work uses the actual clock.
        def clock() -> datetime:
            return now if now is not None else datetime.now(UTC)

        at = clock()
        self.repository.dispatch_due(now=at)
        claim = self.repository.claim(now=at)
        if claim is None:
            return False
        request = claim.job.request
        try:
            if request.kind == "refresh":
                if claim.job.checkpoint_batch_id:
                    batch = self.repository.batch(claim.job.checkpoint_batch_id)
                else:
                    batch = self.fetch(request.stream, at)
                    batch_id = self.repository.ingest(batch)
                    self.repository.checkpoint(claim, batch_id, now=clock())
                market_at = (
                    max(b.close_time for b in batch.bars if b.is_closed)
                    if request.stream.source == "fixture"
                    else batch.fetched_at
                )
                knowledge_at = batch.fetched_at
            else:
                assert request.market_at is not None and request.knowledge_at is not None
                market_at, knowledge_at = request.market_at, request.knowledge_at
            dataset = self.repository.read(
                request.stream,
                market_at=market_at,
                knowledge_at=knowledge_at,
                limit=None if request.rules.demark is not None else 1000,
            )
            result = calculate(dataset, request.rules)
            self.repository.complete(claim, result, now=clock())
        except LeaseLost:
            logger.warning("task_lease_lost")
        except FetchError as exc:
            self.repository.fail(claim, now=clock(), code=exc.code, retryable=exc.retryable)
        except Exception:
            self.repository.fail(claim, now=clock(), code="analysis_failed", retryable=False)
        return True

    def start(self) -> None:
        def loop() -> None:
            while not self.stopping.is_set():
                try:
                    worked = self.run_once()
                except Exception:
                    logger.error("worker_iteration_failed")
                    worked = False
                if not worked:
                    self.stopping.wait(0.5)

        self.thread = Thread(target=loop, name="wheelhouse-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=12)
