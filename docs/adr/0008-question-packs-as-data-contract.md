# Question packs are an external data contract; the engine ships content-free

Interview content — questions, concept notes, and metadata (role, company style, difficulty tags)
— is packaged as external YAML **packs** validated by a public, fail-loud contract
(`coach pack lint`). The engine treats the built-in bank under `data/` as merely the reference
pack. Selection and Supervisor behavior condition on pack metadata (e.g. `target_difficulty`,
role tags): content shapes behavior **through data, never through code changes**.

## Why

The bank is the product's scaling bottleneck: the 2026-07 audit confirmed 15 questions with a
deterministic identical repeat every Session, and issue 0013's breadth tail shows hand-growing a
single built-in bank does not keep pace. Content is also the market surface — VN company-style
packs are the number-one fresh-grad request — and pack authoring is work others (or the Question
Forge, issue 0028) can do only if the boundary is a declared contract rather than repo internals.

The boundary already exists: `bank.py`'s cross-referential validation (every `expected_concepts`
entry must resolve) is the natural plugin seam. Declaring it public inverts engine/content at
near-zero engineering cost, and forces two latent selection-layer fixes into the open —
`target_difficulty` actually driving question choice, and rotation varying across repeat Sessions.

Fail-loud lint extends ADR 0003's ethos to the data boundary: a malformed pack must die at lint
time with a named violation, never mid-interview.

## Considered Options

Growing the built-in bank indefinitely (status quo, issue 0013) was rejected as the *only* path:
it couples every content improvement to a repo commit and keeps the engine and content on one
release cadence. A database-backed bank was rejected for now: YAML packs stay hand-editable,
diff-friendly, and reviewable — properties issue 0013 already established as requirements.
