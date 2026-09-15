"""One advisory inter-process lock, for the two on-disk ledgers a second process can also write.

``threading.Lock`` serialises threads inside one interpreter. Both ledgers are written from more
than one OS process — ``coach session`` and ``coach postmortem`` write the Skill ledger while the
server does, and two ``coach api`` processes sharing one ``/app/state`` volume write the usage
ledger — so the in-process lock leaves the read-modify-write unserialised exactly where it matters.

The lock target is a ``.lock`` SIDECAR, never the data file. ``ledger.save_posteriors`` publishes by
``os.replace``, which swaps the inode: two processes that each opened the *data file* can end up
holding exclusive locks on two different inodes and both believe they are alone. The sidecar is
created once and never replaced or unlinked, so every process locks the same inode. It is a sibling
of the file it guards, so it lives on the same filesystem and the same volume.

flock is advisory and POSIX-only. The deployment target is Linux (Dockerfile: bookworm-slim) and CI
is ubuntu-only, so the import is unconditional; a filesystem that refuses locks (some NFS and FUSE
mounts answer ENOLCK) degrades to the in-process lock with a warning rather than taking down a
Session, because both call sites are forbidden to fail a Candidate over bookkeeping.

This module imports nothing from the package on purpose: ``usage`` cannot import ``ledger``
(ledger -> skill -> evaluator -> llm -> usage is a cycle), so the shared helper has to stand alone.
"""

from __future__ import annotations

import fcntl
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_SUFFIX = ".lock"


def lock_path_for(target: Path) -> Path:
    """The sidecar that guards ``target``."""
    return target.with_name(target.name + LOCK_SUFFIX)


@contextmanager
def locked(target: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on ``target``'s sidecar for the whole block.

    MUST be entered INSIDE the caller's own ``threading.Lock``, never outside it. flock is held per
    *open file description*, so two threads of one process that each open the sidecar get
    independent locks and the second blocks on the first; taking the file lock first and the thread
    lock second is then a lock-order inversion that deadlocks them against each other. Thread lock
    outer, file lock inner.

    For the same reason this must never nest: a second ``locked()`` on the same target from the same
    process opens a second description and blocks the process on itself.
    """
    lock_file = lock_path_for(target)
    handle = None
    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_file.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError as err:
        logger.warning(
            "could not take the inter-process lock at %s (%s: %s); continuing under the in-process "
            "lock only — a concurrent process could interleave with this write.",
            lock_file,
            type(err).__name__,
            err,
        )
        if handle is not None:
            handle.close()
            handle = None
    try:
        yield
    finally:
        if handle is not None:
            handle.close()  # closing the last fd on the description releases the flock
