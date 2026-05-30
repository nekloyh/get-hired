# Adaptive Interview Coach

A multi-agent system that runs an adaptive mock technical interview: it diagnoses a candidate's skill gaps, asks calibrated questions, scores answers against a rubric, and produces a study plan. Built primarily to learn agentic patterns.

## Language

**Candidate**:
The person being interviewed by the system.
_Avoid_: user, student, interviewee

**Session**:
One end-to-end interview run for a Candidate, persisted and resumable.
_Avoid_: conversation, chat

**Interviewer**:
The agent that drives the conversation within a single question — asks the question, and when a **Follow-up** is called for, reasons (with RAG tools) to generate a good one. It does **not** judge or score answers. Owns **depth** mechanically (it runs the micro-loop), but not the judgment that drives it.
_Avoid_: bot, assistant

**Evaluator**:
The single judge of answer quality. Scores every answer against the rubric (1–5 per dimension) and emits `follow_up_recommended`. It is the *only* component that judges; the **Interviewer** never does.
_Avoid_: scorer, grader, critic (critic is the self-critique reflection step, a distinct concept)

**Supervisor**:
A plan-executor with an LLM-judged override. By default it walks the **Topic Plan** produced by diagnosis; it calls the model only to decide whether emerging **Skill** evidence justifies *deviating* from the plan (extra question, skip ahead, switch Skill, or end early). Hard caps (max questions, max time) are deterministic rails. Owns **breadth**.
_Avoid_: orchestrator, router (those name the mechanism, not the role)

**Self-critique**:
A re-evaluation the **Evaluator** triggers on itself when its own score has low confidence — part of producing a trustworthy score for the *current* question. Lives inside the micro-loop, not the Supervisor.
_Avoid_: reflection (too broad), supervisor review

**Topic Plan**:
The ordered list of (Skill, target difficulty, rationale) produced at diagnosis time; the default script the **Supervisor** executes.
_Avoid_: curriculum, roadmap

**Role criticality**:
How much the target role/companies care about a given **Skill** (e.g. MLOps is critical for an MLE role, peripheral for a pure-research role). Derived from `target_role` + `target_companies`. It flexes how *hard* a Skill is probed — never our estimate of the candidate's mastery.
_Avoid_: importance, weight (those are overloaded; "weight" already means rubric-dimension weight)

**Follow-up**:
A probing question asked within the same original question to clarify or stress-test a weak answer. The **Evaluator** decides one is needed (`follow_up_recommended`); the **Interviewer** generates and asks it. Lives inside the micro-loop.
_Avoid_: deep-dive, drill-down

**Micro-loop**:
The within-a-question cycle: Interviewer asks → Candidate answers → Evaluator scores + flags → if a Follow-up is flagged and the safety cap is not hit, Interviewer asks one → repeat; otherwise stop and keep the last score. The cap is a guardrail, not the stop logic.

**Macro-loop**:
The between-questions cycle owned by the **Supervisor**: decide the next move once a question is fully resolved.

**Skill**:
A canonical competency the system assesses (e.g. ml_fundamentals, mlops, system_design, vietnamese_nlp). The taxonomy is fixed.
_Avoid_: topic, area, dimension (a Skill is not a rubric dimension)

## Relationships

- A **Session** belongs to exactly one **Candidate**
- A **Session** runs one **Macro-loop** (Supervisor) containing many **Micro-loops**
- The **Evaluator** decides whether a **Follow-up** is needed; the **Interviewer** generates it; the **Supervisor** is not involved within a question
- **Self-critique** belongs to the **Evaluator**'s micro-loop, not the **Supervisor**
- The **Supervisor** executes the **Topic Plan** unless model judgment says to deviate
- **Role criticality** flexes how hard each **Skill** is probed, not the candidate's estimated mastery
- A question targets exactly one **Skill**

## Example dialogue

> **Dev:** "When the candidate gives a weak MLOps answer, who decides to dig in?"
> **Architect:** "The **Evaluator** does — it scores the answer and raises `follow_up_recommended`. The **Interviewer** then *generates* the **Follow-up** (using its RAG tool) and asks it. This repeats inside the **Micro-loop** until the Evaluator stops flagging or the cap fires. Only once the question is fully resolved does control return to the **Supervisor**, which owns the **Macro-loop** and decides whether to switch **Skill** or end the **Session**."

## Flagged ambiguities

- "deep-dive" appeared in the V2 plan as a *Supervisor* action — resolved: digging into one question is a **Follow-up** owned by the **Interviewer**, not a Supervisor move. Supervisor breadth ≠ Interviewer depth.
- "self_critique" appeared in the V2 plan as a *Supervisor* action — resolved: re-checking a low-confidence score is part of finishing the current question's judgment, so it's **Self-critique** inside the **Evaluator**'s micro-loop. Same principle as deep-dive: the Supervisor only owns between-question moves.
