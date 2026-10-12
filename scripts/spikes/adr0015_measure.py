"""ADR 0015 gate measurements (#161): JSONL versus SQLite rail cost, and a migration dry-run.

Spike code. It lives in scripts/spikes/ because ADR 0015 is Proposed, and nothing in src/ may depend
on a Proposed ADR. The SQLite side is a prototype of the schema the ADR sketches. The JSONL side is
always the real `interview_coach.usage` and `interview_coach.ledger` code, called with an explicit
`path=`.

  uv run python scripts/spikes/adr0015_measure.py bench
  uv run python scripts/spikes/adr0015_measure.py migrate <usage.jsonl> [<skill-ledger.json>]

`migrate` reads copies only: it hashes its inputs before and after and refuses if they change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from interview_coach import ledger, usage

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY,           -- write order, which the undo rows (released, session_run) need
    ts TEXT, day TEXT, kind TEXT NOT NULL, session TEXT NOT NULL DEFAULT '',
    provider TEXT, model TEXT, prompt INTEGER, completion INTEGER,
    identity TEXT, questions INTEGER, baseline INTEGER,
    payload TEXT NOT NULL             -- the original row, verbatim: the import loses nothing
);
CREATE INDEX IF NOT EXISTS usage_by_day ON usage_events(day, kind, provider);
CREATE INDEX IF NOT EXISTS usage_by_session ON usage_events(session);
CREATE TABLE IF NOT EXISTS skill_snapshots (
    id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL, completed_at REAL NOT NULL,
    source TEXT NOT NULL, skills_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS skills_by_candidate ON skill_snapshots(candidate_id, completed_at);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def _int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _row(entry: dict) -> tuple:
    """One ledger row as a table row. A value usage.py would refuse to int() is stored NULL, so the
    SQL aggregates skip exactly the rows the Python ones skip."""
    has_tokens = "prompt_tokens" in entry or "completion_tokens" in entry
    kind = str(entry.get("kind") or ("tokens" if has_tokens else "other"))
    ts = entry.get("ts")
    return (
        None if ts is None else str(ts),
        None if ts is None else str(ts)[:10],
        kind,
        str(entry.get("session", "")),
        None if entry.get("provider") is None else str(entry["provider"]),
        entry.get("model"),
        _int(entry.get("prompt_tokens")),
        _int(entry.get("completion_tokens")),
        None if entry.get("identity") is None else str(entry["identity"]),
        _int(entry.get("questions")),
        _int(entry.get("baseline")),
        json.dumps(entry, sort_keys=True, ensure_ascii=False),
    )


INSERT = (
    "INSERT INTO usage_events (ts, day, kind, session, provider, model, prompt, completion, identity, "
    "questions, baseline, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
)


def import_usage(conn: sqlite3.Connection, jsonl: Path) -> tuple[int, int]:
    """Import every parseable dict row in write order, in one transaction. Returns (imported, skipped)."""
    rows, skipped = [], 0
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(entry, dict):
            skipped += 1
            continue
        rows.append(_row(entry))
    conn.execute("BEGIN IMMEDIATE")
    conn.executemany(INSERT, rows)
    conn.execute("COMMIT")
    return len(rows), skipped


# --- The SQL twins of the usage.py aggregates the rails call -------------------------------------

_TOKENS = "prompt IS NOT NULL AND completion IS NOT NULL"


def sql_usage_for_day(conn: sqlite3.Connection, day: str) -> dict[str, dict[str, int]]:
    out = {}
    for provider, prompt, completion, calls in conn.execute(
        f"SELECT provider, SUM(prompt), SUM(completion), COUNT(*) FROM usage_events "
        f"WHERE day = ? AND {_TOKENS} AND provider IS NOT NULL GROUP BY provider",
        (day,),
    ):
        out[provider] = {"prompt": prompt, "completion": completion, "total": prompt + completion, "calls": calls}
    return out


def sql_sessions_for_day(conn: sqlite3.Connection, day: str) -> dict[str, int]:
    return dict(
        conn.execute(
            f"SELECT session, SUM(prompt + completion) FROM usage_events WHERE day = ? AND {_TOKENS} GROUP BY session",
            (day,),
        ).fetchall()
    )


def sql_session_run_spend(conn: sqlite3.Connection, session: str) -> int:
    (lifetime,) = conn.execute(
        f"SELECT COALESCE(SUM(prompt + completion), 0) FROM usage_events WHERE session = ? AND {_TOKENS}", (session,)
    ).fetchone()
    found = conn.execute(
        "SELECT baseline FROM usage_events WHERE session = ? AND kind = 'session_run' AND baseline IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (session,),
    ).fetchone()
    return max(0, lifetime - (found[0] if found else 0))


def sql_questions_today(conn: sqlite3.Connection, identity: str, day: str) -> int:
    (total,) = conn.execute(
        "SELECT COALESCE(SUM(CASE kind WHEN 'questions_released' THEN -questions ELSE questions END), 0) "
        "FROM usage_events WHERE day = ? AND identity = ? AND kind IN ('questions', 'questions_released') "
        "AND questions IS NOT NULL",
        (day, identity),
    ).fetchone()
    return max(0, total)


def sql_quota_exhausted_today(conn: sqlite3.Connection, provider: str, day: str, session: str = "") -> bool:
    """The latch is scanned in write order in usage.py; here the same scan runs over day+provider only."""
    dead = False
    for kind, granted, prompt in conn.execute(
        "SELECT kind, session, prompt FROM usage_events WHERE day = ? AND provider = ? ORDER BY id", (day, provider)
    ):
        if kind == "quota_exhausted":
            dead = True
        elif kind == "quota_retry":
            if not granted or granted == session:
                dead = False
        elif prompt is not None or kind == "tokens":
            dead = False
    return dead


# --- bench ------------------------------------------------------------------------------------------


def _synthetic(n: int, *, days: int = 30, seed: int = 7) -> list[dict]:
    """A ledger shaped like the real one: ~97% token rows in Session runs, plus the bookkeeping rows."""
    rng = random.Random(seed)
    today = usage.utc_date()
    base = time.mktime(time.strptime(today, "%Y-%m-%d"))
    rows: list[dict] = []
    session = 0
    while len(rows) < n:
        session += 1
        sid = f"s{session}"
        day_offset = rng.randrange(days)
        stamp = time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(base - day_offset * 86_400 + rng.randrange(80_000))
        )
        rows.append({"ts": stamp, "kind": "questions", "identity": "id0", "questions": 5})
        rows.append({"ts": stamp, "kind": "session_run", "session": sid, "baseline": 0})
        for _ in range(rng.randrange(10, 25)):
            rows.append(
                {
                    "ts": stamp,
                    "provider": "openai" if rng.random() < 0.9 else "groq",
                    "model": "gpt-5.4-mini",
                    "prompt_tokens": rng.randrange(300, 3000),
                    "completion_tokens": rng.randrange(50, 800),
                    "session": sid,
                }
            )
    return rows[:n]


def _median_ms(fn: Callable[[], object], repeat: int) -> float:
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples)


def _bench_one(n: int, today: str) -> str:
    """One table row: the median cost of a node boundary's rails and of one write, at ``n`` rows."""
    with tempfile.TemporaryDirectory() as tmp:
        jsonl = Path(tmp) / "usage-ledger.jsonl"
        rows = _synthetic(n)
        jsonl.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        conn = connect(Path(tmp) / "coach.sqlite")
        import_usage(conn, jsonl)
        sid = rows[-1].get("session", "s1")

        # One graph-node boundary of budget_stop_reason: the quota latch, the run spend (lifetime and
        # baseline) and the day's remaining budget. #125 counts ~2 boundaries per question.
        def jsonl_boundary() -> None:
            usage.quota_exhausted_today("openai", path=jsonl)
            usage.session_run_spend(sid, path=jsonl)
            usage.usage_for_day(today, path=jsonl)

        def sql_boundary() -> None:
            sql_quota_exhausted_today(conn, "openai", today)
            sql_session_run_spend(conn, sid)
            sql_usage_for_day(conn, today)

        repeat = 15 if n > 10_000 else 40
        jsonl_read = _median_ms(jsonl_boundary, repeat)
        sql_read = _median_ms(sql_boundary, repeat)

        def jsonl_write() -> None:
            usage.record_usage("openai", "gpt-5.4-mini", prompt_tokens=1000, completion_tokens=200, path=jsonl)

        def sql_write() -> None:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                INSERT,
                _row(
                    {
                        "ts": usage._now_ts(),
                        "provider": "openai",
                        "model": "m",
                        "prompt_tokens": 1000,
                        "completion_tokens": 200,
                    }
                ),
            )
            conn.execute("COMMIT")

        jsonl_wr = _median_ms(jsonl_write, 200)
        sql_wr = _median_ms(sql_write, 200)
        conn.close()
    return f"| {n:,} | {jsonl_read:.2f} | {sql_read:.2f} | {jsonl_wr:.3f} | {sql_wr:.3f} |"


def bench() -> None:
    today = usage.utc_date()
    print("| rows | JSONL ms / node boundary | SQLite ms / node boundary | JSONL ms / write | SQLite ms / write |")
    print("|---:|---:|---:|---:|---:|")
    for n in (1_500, 10_000, 50_000):
        print(_bench_one(n, today))


# --- migrate ----------------------------------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compare_usage(conn: sqlite3.Connection, jsonl: Path, label: str) -> int:
    """Every aggregate a rail or `coach usage` reads, on every key present, Python versus SQL."""
    rows = list(usage._all_rows(jsonl))
    days = sorted({str(r["ts"])[:10] for r in rows if "ts" in r})
    sessions = sorted({str(r.get("session", "")) for r in rows})
    identities = sorted({str(r["identity"]) for r in rows if "identity" in r})
    providers = sorted({str(r["provider"]) for r in rows if "provider" in r})
    checks = mismatches = 0

    def same(name: str, python: object, sql: object) -> None:
        nonlocal checks, mismatches
        checks += 1
        if python != sql:
            mismatches += 1
            print(f"    MISMATCH {name}: python={python!r} sql={sql!r}")

    for day in days:
        same(f"usage_for_day({day})", usage.usage_for_day(day, path=jsonl), sql_usage_for_day(conn, day))
        same(f"sessions_for_day({day})", usage.sessions_for_day(day, path=jsonl), sql_sessions_for_day(conn, day))
        for identity in identities:
            same(
                f"questions_today({day})",
                usage.questions_today(identity, day=day, path=jsonl),
                sql_questions_today(conn, identity, day),
            )
        for provider in providers:
            same(
                f"quota_exhausted_today({provider},{day})",
                usage.quota_exhausted_today(provider, day=day, path=jsonl),
                sql_quota_exhausted_today(conn, provider, day),
            )
    for session in sessions:
        same(
            f"session_run_spend({session})",
            usage.session_run_spend(session, path=jsonl),
            sql_session_run_spend(conn, session),
        )
    # Lossless: the payload column round-trips every imported row, in write order.
    replayed = [json.loads(p) for (p,) in conn.execute("SELECT payload FROM usage_events ORDER BY id")]
    same("payload round-trip", rows, replayed)
    print(
        f"  {label}: {len(rows)} rows, {len(days)} day(s), {len(sessions)} session id(s), "
        f"{len(identities)} identity(ies): {checks} comparisons, {mismatches} mismatch(es)"
    )
    return mismatches


def migrate(usage_path: Path, skill_path: Path | None) -> int:
    inputs = [p for p in (usage_path, skill_path) if p]
    before = {p: _sha(p) for p in inputs}
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "coach.sqlite"
        conn = connect(db)
        imported, skipped = import_usage(conn, usage_path)
        print(f"  usage import: {imported} row(s), {skipped} unparseable line(s) skipped (usage.py skips them too)")
        failures += _compare_usage(conn, usage_path, "live database")

        if skill_path:
            data = json.loads(skill_path.read_text(encoding="utf-8"))
            candidates = [k for k in data if k != "_meta"]
            conn.execute("BEGIN IMMEDIATE")
            for cid in candidates:
                record = data[cid]
                conn.execute(
                    "INSERT INTO skill_snapshots (candidate_id, completed_at, source, skills_json) VALUES (?,?,?,?)",
                    (cid, float(record["completed_at"]), "import", json.dumps(record["skills"], sort_keys=True)),
                )
            conn.execute("COMMIT")
            now = time.time()
            for cid in candidates:
                completed_at, skills_json = conn.execute(
                    "SELECT completed_at, skills_json FROM skill_snapshots WHERE candidate_id = ? "
                    "ORDER BY completed_at DESC, id DESC LIMIT 1",
                    (cid,),
                ).fetchone()
                # The latest snapshot, rebuilt as a one-record ledger, must give load_priors' exact answer.
                rebuilt = Path(tmp) / f"rebuilt-{cid}.json"
                rebuilt.write_text(
                    json.dumps(
                        {
                            "_meta": data.get("_meta", {}),
                            cid: {"completed_at": completed_at, "skills": json.loads(skills_json)},
                        }
                    ),
                    encoding="utf-8",
                )
                original = ledger.load_priors(skill_path, cid, now=now)
                again = ledger.load_priors(rebuilt, cid, now=now)
                ok = original == again
                failures += 0 if ok else 1
                print(f"  skill ledger {cid}: {len(json.loads(skills_json))} skill(s), load_priors identical: {ok}")

        # Backup and restore through SQLite's online backup API, then re-run every comparison on the copy.
        restored_path = Path(tmp) / "restored.sqlite"
        restored = sqlite3.connect(restored_path)
        conn.backup(restored)
        restored.close()
        conn.close()
        failures += _compare_usage(connect(restored_path), usage_path, "restored backup")

    for p in inputs:
        if _sha(p) != before[p]:
            print(f"  INPUT CHANGED: {p}")
            failures += 1
    print(f"  inputs unchanged: {all(_sha(p) == before[p] for p in inputs)}")
    print(f"MIGRATION DRY-RUN: {'PASS' if failures == 0 else f'FAIL ({failures})'}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bench")
    m = sub.add_parser("migrate")
    m.add_argument("usage", type=Path)
    m.add_argument("skill", type=Path, nargs="?")
    args = parser.parse_args()
    if args.cmd == "bench":
        bench()
        return 0
    return migrate(args.usage, args.skill)


if __name__ == "__main__":
    raise SystemExit(main())
