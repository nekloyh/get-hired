from __future__ import annotations

from interview_coach.ui import render_skill_state_bar, render_skill_state_rows


def test_render_skill_state_bar_is_stable_width_and_bounded():
    assert render_skill_state_bar(0.5, width=10) == "[#####-----]"
    assert render_skill_state_bar(-1.0, width=4) == "[----]"
    assert render_skill_state_bar(2.0, width=4) == "[####]"


def test_render_skill_state_rows_include_mastery_confidence_and_criticality():
    rows = render_skill_state_rows(
        {
            "skill_states": {
                "mlops": {"skill": "mlops", "alpha": 3.0, "beta": 1.0},
            },
            "skill_metadata": {
                "mlops": {"role_criticality": "must_have"},
            },
        },
        width=8,
    )

    assert rows == [
        "mlops              [######--] mastery=  75% confidence=  55% criticality=must_have"
    ]
