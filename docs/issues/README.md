# Issues — slice specs, and how work is tracked

## Where status lives

Work, its order and its state live in the **[GitHub milestones](https://github.com/nekloyh/get-hired/milestones)**
and nowhere else: `v0.3.0 Stable`, then `v0.4.0 Foundation`. `Later` is frozen until both close, and
its description says so.

| Question | The one place that answers it |
|---|---|
| What is being worked on, in what order, and is it done? | GitHub milestones and issues |
| What shipped, and what was still red when it did? | [`CHANGELOG.md`](../../CHANGELOG.md) |
| What was decided, and is it binding yet? | the `Status:` line of each [ADR](../adr/) |

Every other document in this repo is one of two kinds. **Evergreen** documents say how and why and
contain no status. **Records** are dated measurements in [`../audits/`](../audits/) and are never edited
after their date. A document that repeats status drifts out of date: `CLAUDE.md` said the judge was
green for two months after its gate went red. That is why this rule exists (#140).

## IDs

New work gets a GitHub issue number, `#NN`, and nothing else. Older aliases still resolve:

| Alias | Means |
|---|---|
| `0001`–`0037` | a slice spec in this directory (below) |
| `R-01`–`R-33` | remediation backlog item `#(55+NN)`, i.e. GH #56–#88 |
| `M0a`…`M6`, `F1`, `Q1`–`Q3`, `U1`–`U4`, `A1`, `A2`, `V1`, `V2`, `X1`, `X2` | milestones and work IDs of the [2026-09-13 implementation plan](../audits/implementation-plan-2026-09-13.md) |
| `QA-NN`, `M0-NN`, `M1-NN`, `M2-N` | rows of the [QA report](../audits/qa-report-2026-09-15.md) and the [milestone report](../audits/milestone-v0.1.0-pilot-2026-09-15.md) |
| `E1`–`E6` | experiments named in the ADR amendments |

## Citations

Cite `module.symbol`, for example `ledger.save_posteriors` or `usage.reconcile_accounting`, not
`file:line`. A line number is true for one commit. When #124 split `web_api.py` from 1,375 lines to
329, every open issue citing `web_api.py:1097` broke at the same moment. A record may cite lines
because it names the commit it was measured at.

## Slice specs

`00NN-*.md` are the vertical-slice specs: contracts and acceptance criteria, numbered in build
order. Their `## Status` sections are historical; the GitHub issue is the status. To learn the
design, start with the critical path `0001 → 0002 → 0005 → {0006, 0007, 0009} → 0010`.

## Gates every milestone keeps

These rules come from the evidence contract in the
[2026-09-13 plan](../audits/implementation-plan-2026-09-13.md#evidence-contract-for-every-milestone),
which also holds the original M3–M6 definitions the `Later` items descend from.

- **Missing evidence is not PASS.** A failed gate shifts the date; a date never waives a gate.
- A result names its commit SHA, the judge fingerprint (#141), the pack, the role → model mapping and
  the decoding parameters. Fakes and demo mode prove mechanics, never live quality.
- Live provider runs need an explicit token budget, set before the run. CI never spends money.
- On a red gate, keep the previous working path, fix the failing slice and rerun the affected checks.
  Don't widen a band or relabel a result to make it green.
