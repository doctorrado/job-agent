"""The JobSource contract every adapter implements.

Each adapter knows the shape of exactly one source's raw data and is
responsible for mapping it into `Job` itself — nothing downstream (dedupe,
storage, scoring) ever needs to know which source a Job came from or what
that source's raw payload looked like.

Deliberately not handled here: what to do when a source fails. `fetch()`
just raises. Whether a network error from one source should abort the whole
run or just get logged and skipped is a decision for whatever calls multiple
sources together, not for each adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from jobagent.models.job import Job


class JobSource(ABC):
    #: short, stable identifier used as Job.source and in logs, e.g. "remotive"
    name: str

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Return normalized jobs from this source."""
        ...
