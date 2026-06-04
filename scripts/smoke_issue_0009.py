"""Live smoke for issue 0009's Diagnostic agent — hits the real configured provider.

Unlike ``smoke_issue_0007.py`` (offline fakes), this exercises the *primary* Topic Plan path against
the real LLM to raise the audit value of the agent cutover: it proves the single-shot agent returns a
schema-valid plan over the live provider, and shows how the agent's ordering/difficulty differs from
the deterministic offline fallback for the same Candidate.

Run: ``uv run python scripts/smoke_issue_0009.py``. Skips cleanly (exit 0) when no provider is
configured; exits non-zero if a live plan violates an invariant.
"""

from __future__ import annotations

import sys

from interview_coach.config import load_settings
from interview_coach.diagnostic import (
    SKILLS,
    CandidateProfile,
    DiagnosticResult,
    TopicPlanSource,
    diagnose,
)
from interview_coach.llm import build_client

PROFILES: tuple[CandidateProfile, ...] = (
    CandidateProfile(
        target_role="machine learning engineer",
        claimed_skills={"mlops": 4, "ml_fundamentals": 3},
    ),
    CandidateProfile(
        target_role="research scientist",
        claimed_skills={"deep_learning": 5, "mlops": 2},
        target_companies=("VinAI",),
    ),
)


def _check_plan(result: DiagnosticResult) -> list[str]:
    """Return a list of invariant violations (empty == healthy)."""
    problems: list[str] = []
    skills = [entry.skill for entry in result.topic_plan]
    if set(skills) != set(SKILLS):
        problems.append(f"skill set mismatch: got {sorted(set(skills))}, want {sorted(SKILLS)}")
    if len(skills) != len(set(skills)):
        problems.append(f"duplicate skills in plan: {skills}")
    for entry in result.topic_plan:
        if not 1 <= entry.target_difficulty <= 5:
            problems.append(f"{entry.skill}: difficulty {entry.target_difficulty} out of 1–5")
        if not entry.rationale.strip():
            problems.append(f"{entry.skill}: empty rationale")
    return problems


def _print_order(label: str, result: DiagnosticResult) -> None:
    order = " > ".join(f"{e.skill}(d{e.target_difficulty})" for e in result.topic_plan)
    print(f"  [{label:<13} source={result.topic_plan_source.value}] {order}")


def main() -> int:
    settings = load_settings()
    if not settings.configured:
        print(
            f"SKIP: primary provider {settings.primary_provider!r} not configured "
            "(set up .env to run the live smoke).",
            file=sys.stderr,
        )
        return 0

    client = build_client(settings)
    print(f"Live Diagnostic smoke against primary provider {settings.primary_provider!r}.\n")

    violations: list[str] = []
    for n, profile in enumerate(PROFILES, start=1):
        print(f"=== PROFILE {n}: {profile.target_role} (claims {dict(profile.claimed_skills)}) ===")
        live = diagnose(profile, client)
        offline = diagnose(profile, None)

        if live.topic_plan_source is not TopicPlanSource.LLM:
            violations.append(f"profile {n}: expected source=llm, got {live.topic_plan_source.value}")
        problems = _check_plan(live)
        violations.extend(f"profile {n}: {p}" for p in problems)

        # Differential: the agent's plan vs the deterministic fallback for the same Candidate.
        _print_order("LLM AGENT", live)
        _print_order("DETERMINISTIC", offline)
        for entry in live.topic_plan:
            print(f"    - {entry.skill}: {entry.rationale}")
        print()

    if violations:
        print("FAIL — live plan invariant violations:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print("OK — every live Topic Plan was schema-valid and complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
