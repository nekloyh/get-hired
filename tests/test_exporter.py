"""Durability of the Markdown export's on-disk publish (NEW-04)."""

from __future__ import annotations

import errno
import os
import tempfile
from pathlib import Path

import pytest

from interview_coach.exporter import export_session_markdown

_MINIMAL = {"session_id": "durability", "status": "complete", "question_count": 1, "transcript": []}


def test_the_export_is_fsynced_and_published_by_rename(tmp_path, monkeypatch):
    # The export is the one artifact a Candidate keeps, and it lives on the same /state volume as the
    # ledger — so it gets the ledger's publish, not a truncating write. `st_ino` proves the sync
    # landed on the file that became the export; `st_size` proves that file held the report.
    target = tmp_path / "session.md"
    real_fsync, real_replace = os.fsync, os.replace
    synced: list[os.stat_result] = []
    published: list[tuple[Path, Path]] = []

    def spy_fsync(fd):
        synced.append(os.fstat(fd))
        return real_fsync(fd)

    def spy_replace(src, dst, *args, **kwargs):
        published.append((Path(src), Path(dst)))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)

    export_session_markdown(_MINIMAL, target)

    assert [dst for _src, dst in published] == [target]
    # A sibling, not the system temp dir: os.replace raises EXDEV across the /state mount boundary.
    assert published[0][0].parent == tmp_path
    assert synced and synced[0].st_size == target.stat().st_size > 0
    assert target.stat().st_ino == synced[0].st_ino


def test_a_write_that_dies_mid_flight_never_truncates_the_previous_export(tmp_path, monkeypatch):
    # ENOSPC arrives at `write`, not at `replace` — the disk fills while the buffer drains. Staging
    # makes that a no-op: yesterday's report survives, and no `.session.md.*.tmp` litters the volume
    # that is already full.
    target = tmp_path / "session.md"
    export_session_markdown({**_MINIMAL, "session_id": "yesterday"}, target)
    before = target.read_bytes()
    real_named_temporary_file = tempfile.NamedTemporaryFile

    def half_written_tempfile(*args, **kwargs):
        handle = real_named_temporary_file(*args, **kwargs)

        def die_mid_write(_payload):
            raise OSError(errno.ENOSPC, "No space left on device")

        handle.write = die_mid_write
        return handle

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", half_written_tempfile)

    with pytest.raises(OSError):
        export_session_markdown(_MINIMAL, target)

    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["session.md"]
