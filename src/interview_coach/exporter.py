"""Session Markdown export for portfolio artifacts (slice 0011)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .skill import SkillState


def _display_stop_reason(stop_reason: Any) -> str:
    text = "" if stop_reason is None else str(stop_reason)
    if text == "safety_cap":
        return "unresolved_by_safety_cap"
    if text == "follow_up_unavailable":
        return "degraded_follow_up_unavailable"
    if text == "failed":
        return "failed_recorded_and_skipped"
    return text


def export_session_markdown(session_state: Mapping[str, Any], path: str | Path) -> Path:
    """Write a readable Markdown export of a completed Session."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_session_markdown(session_state), encoding="utf-8")
    return output


def render_session_markdown(session_state: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Interview Session: {_md(session_state.get('session_id', 'unknown-session'))}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Status: `{_md(session_state.get('status', 'unknown'))}`")
    lines.append(f"- Stop reason: `{_md(session_state.get('stop_reason', 'n/a'))}`")
    lines.append(f"- Questions: `{session_state.get('question_count', 0)}`")
    lines.append(f"- Language mode: `{_md(session_state.get('language_mode', 'en'))}`")
    lines.append("")
    _append_skill_states(lines, session_state)
    _append_ledger_deltas(lines, session_state)
    _append_topic_plan(lines, session_state)
    _append_transcript(lines, session_state)
    _append_supervisor_decisions(lines, session_state)
    _append_study_plan(lines, session_state.get("study_plan"))
    return "\n".join(lines).rstrip() + "\n"


def _append_skill_states(lines: list[str], session_state: Mapping[str, Any]) -> None:
    lines.append("## Final Skill States")
    lines.append("")
    lines.append("| Skill | Mastery | Confidence | Beta | Role criticality |")
    lines.append("| --- | ---: | ---: | --- | --- |")
    metadata = session_state.get("skill_metadata", {})
    for skill, raw in sorted(session_state.get("skill_states", {}).items()):
        state = SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"]))
        meta = metadata.get(skill, {})
        lines.append(
            f"| `{_md(skill)}` | {state.mastery:.3f} | {state.confidence:.3f} | "
            f"alpha={state.alpha:.2f}, beta={state.beta:.2f} | "
            f"{_md(meta.get('role_criticality', 'unknown'))} |"
        )
    lines.append("")


def _append_ledger_deltas(lines: list[str], session_state: Mapping[str, Any]) -> None:
    """Since-last-session mastery deltas for a returning Candidate (issue 0023). Cold start renders nothing."""
    prior = session_state.get("ledger_prior_mastery")
    if not prior:
        return
    skill_states = session_state.get("skill_states", {})
    lines.append("## Since Previous Session")
    lines.append("")
    lines.append("| Skill | Previous | Now | Change |")
    lines.append("| --- | ---: | ---: | ---: |")
    for skill in sorted(prior):
        raw = skill_states.get(skill)
        if raw is None:
            continue
        before = float(prior[skill])
        after = SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"])).mastery
        lines.append(f"| `{_md(skill)}` | {before:.3f} | {after:.3f} | {after - before:+.3f} |")
    lines.append("")


def _append_topic_plan(lines: list[str], session_state: Mapping[str, Any]) -> None:
    if not session_state.get("topic_plan"):
        return
    lines.append("## Topic Plan")
    lines.append("")
    lines.append("| # | Skill | Difficulty | Rationale |")
    lines.append("| ---: | --- | ---: | --- |")
    for i, item in enumerate(session_state.get("topic_plan", []), start=1):
        lines.append(
            f"| {i} | `{_md(item.get('skill'))}` | {item.get('target_difficulty')} | "
            f"{_md(item.get('rationale'))} |"
        )
    lines.append("")


def _append_transcript(lines: list[str], session_state: Mapping[str, Any]) -> None:
    lines.append("## Transcript")
    lines.append("")
    for i, item in enumerate(session_state.get("transcript", []), start=1):
        lines.append(f"### Question {i}: `{_md(item.get('skill'))}`")
        lines.append("")
        if item.get("stop_reason") == "failed":
            lines.append(
                f"**Question failed and was skipped** — `{_md(item.get('error', 'unknown error'))}`; "
                f"stop: `{_md(_display_stop_reason(item.get('stop_reason')))}`."
            )
        else:
            score_label = "Kept score" if item.get("stop_reason") == "safety_cap" else "Resolved score"
            lines.append(
                f"{score_label}: **{float(item.get('resolved_weighted_score', 0)):.2f}/5**; "
                f"confidence: **{float(item.get('resolved_confidence', 0)):.2f}**; "
                f"evidence weight: **{float(item.get('evidence_weight', 0)):.2f}**; "
                f"stop: `{_md(_display_stop_reason(item.get('stop_reason')))}`."
            )
        lines.append("")
        for turn_n, turn in enumerate(item.get("turns", []), start=1):
            kind = "Follow-up" if turn.get("is_follow_up") else "Question"
            lines.append(f"#### Turn {turn_n}: {kind}")
            lines.append("")
            lines.append(f"**Interviewer:** {_md(turn.get('question'))}")
            lines.append("")
            lines.append(f"**Candidate:** {_md(turn.get('answer'))}")
            if turn.get("grounding_concept_id"):
                lines.append("")
                lines.append(
                    f"Grounded by: `{_md(turn.get('grounding_concept_id'))}` "
                    f"({_md(turn.get('grounding_concept_title'))})"
                )
            _append_evaluation(lines, turn.get("evaluation", {}))
            trace = turn.get("trace", {})
            if trace.get("evaluator_self_critique_triggers"):
                lines.append(
                    f"Self-critique triggers: `{_md(', '.join(trace['evaluator_self_critique_triggers']))}`"
                )
            if trace.get("concept_lookup_query"):
                lines.append(
                    f"Concept lookup: `{_md(trace.get('concept_lookup_query'))}` -> "
                    f"`{_md(trace.get('concept_hit_id') or 'none')}`"
                )
            lines.append("")


def _append_evaluation(lines: list[str], evaluation: Mapping[str, Any]) -> None:
    lines.append("")
    lines.append("| Dimension | Score | Evidence |")
    lines.append("| --- | ---: | --- |")
    for dim, score in evaluation.get("dimensions", {}).items():
        if not isinstance(score, Mapping):
            continue
        lines.append(f"| {_md(dim)} | {score.get('score')} | {_md(score.get('evidence'))} |")
    lines.append("")
    lines.append(
        f"Weighted score: **{float(evaluation.get('weighted_score', 0)):.2f}/5**; "
        f"confidence: **{float(evaluation.get('confidence', 0)):.2f}**; "
        f"follow-up recommended: `{evaluation.get('follow_up_recommended')}`."
    )
    if rationale := evaluation.get("follow_up_rationale"):
        lines.append(f"Rationale: {_md(rationale)}")
    if fixes := evaluation.get("delivery_fixes"):
        # issue 0024: weak English delivery comes with concrete phrase-level fixes.
        lines.append("")
        lines.append("English delivery fixes:")
        for fix in fixes:
            lines.append(f"- {_md(fix)}")
    if panel := evaluation.get("panel"):
        # issue 0027: the committee packet — each voice's one-paragraph scorecard and the
        # disagreement, the artifact a real hiring-committee debrief produces.
        skeptic = panel.get("skeptic", {})
        advocate = panel.get("advocate", {})
        lines.append("")
        lines.append("**Committee packet (panel verdict)**")
        lines.append("")
        lines.append(
            f"- Escalated on `{_md(', '.join(panel.get('triggers', [])))}`: first pass "
            f"{float(panel.get('initial_score', 0)):.2f}/5 (confidence "
            f"{float(panel.get('initial_confidence', 0)):.2f}) → verdict "
            f"{float(evaluation.get('weighted_score', 0)):.2f}/5; committee disagreement "
            f"{float(panel.get('disagreement', 0)):.2f} points."
        )
        lines.append(
            f"- Skeptic ({float(skeptic.get('recommended_score', 0)):g}/5): {_md(skeptic.get('argument'))} "
            f"— evidence: {_md(skeptic.get('key_evidence'))}"
        )
        lines.append(
            f"- Advocate ({float(advocate.get('recommended_score', 0)):g}/5): {_md(advocate.get('argument'))} "
            f"— evidence: {_md(advocate.get('key_evidence'))}"
        )
    if evaluation.get("evidence_degraded"):
        # issue 0033: every citation was unverifiable — the score stands but its audit trail does not.
        lines.append(
            "> ⚠️ Evidence degraded: every citation was unverifiable, so the score is kept but its "
            "audit trail is not — confidence has been capped."
        )


def _append_supervisor_decisions(lines: list[str], session_state: Mapping[str, Any]) -> None:
    if not session_state.get("supervisor_decisions"):
        return
    lines.append("## Supervisor Decisions")
    lines.append("")
    for decision in session_state["supervisor_decisions"]:
        lines.append(
            f"- After Q{decision.get('after_question')}: `{_md(decision.get('action'))}` "
            f"(deviation=`{decision.get('deviation')}`) - {_md(decision.get('llm_reasoning'))}"
        )
    lines.append("")


def _append_study_plan(lines: list[str], plan: Any) -> None:
    lines.append("## Study Plan")
    lines.append("")
    if not isinstance(plan, Mapping):
        lines.append("No Study Plan recorded.")
        lines.append("")
        return
    lines.append(
        f"Readiness estimate: **{float(plan.get('readiness_estimate', 0)):.0%}**. "
        f"{_md(plan.get('readiness_rationale'))}"
    )
    lines.append("")
    lines.append("### Prioritized Topics")
    lines.append("")
    for topic in plan.get("prioritized_topics", []):
        lines.append(
            f"{topic.get('priority')}. **{_md(topic.get('title'))}** (`{_md(topic.get('skill'))}`) - "
            f"{_md(topic.get('rationale'))}"
        )
        lines.append(
            f"   Target: {_md(topic.get('target_mastery'))}; current mastery "
            f"{float(topic.get('mastery', 0)):.0%}; criticality `{_md(topic.get('role_criticality'))}`."
        )
        for resource in topic.get("resources", []):
            lines.append(f"   - [{_md(resource.get('title'))}]({resource.get('url')})")
    lines.append("")
    lines.append("### Two-Week Schedule")
    lines.append("")
    lines.append("| Day | Focus | Resources | Outcome |")
    lines.append("| ---: | --- | --- | --- |")
    for item in plan.get("schedule", []):
        resources = ", ".join(
            f"[{_md(resource.get('title'))}]({resource.get('url')})" for resource in item.get("resources", [])
        )
        lines.append(
            f"| {item.get('day')} | {_md(item.get('focus'))} | {resources} | {_md(item.get('outcome'))} |"
        )
    lines.append("")
    lines.append("### Milestones")
    lines.append("")
    for milestone in plan.get("milestones", []):
        lines.append(
            f"- Week {milestone.get('week')}: {_md(milestone.get('description'))} "
            f"(evidence: {_md(milestone.get('evidence'))})"
        )
    lines.append("")


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|")
