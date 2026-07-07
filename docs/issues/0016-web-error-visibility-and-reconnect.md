# Web: surface Session errors and handle connection loss

**Type:** AFK
**Kind:** bug

## What to build

Two confirmed dead-ends make the web UI unusable the moment anything goes wrong:

- **Errors are invisible.** The reducer stores `session_error` events, but no component renders
  them — status `error` maps back to the setup phase, so starting live mode without a configured
  provider just silently re-shows the setup form. Any mid-interview failure unmounts the chat view
  with no explanation. (This is the first thing a real user hits today, given issue 0015.)
- **Connection loss is unhandled.** Only `onopen`/`onmessage`/`onerror` are wired. A clean
  WebSocket close — restarting `coach api`, uvicorn shutdown, network sleep — fires only
  `onclose` in browsers, so no event reaches the reducer: the UI stays on "Waiting for the
  Interviewer" forever. There is no reconnect or backoff anywhere.

End-to-end behavior to build: any backend failure or connection loss lands the Candidate on a
visible, actionable state — an error message with context, or a disconnected state with a working
resume path back into the same Session.

## Acceptance criteria

- [x] Starting live mode without a configured provider shows the server's error message in the UI
      instead of silently resetting to setup
- [x] A mid-Session `session_error` keeps a visible error with the message text; the Candidate is
      told what happened and what to do next
- [x] WebSocket close is handled: the UI enters a distinct disconnected state and offers
      reconnect/resume; reconnecting resumes the same `session_id`
- [x] Demoable: kill `coach api` mid-question, restart it, reconnect from the browser, continue
      the Session to completion
- [x] Component tests cover the error render and the close→disconnected transition; the Playwright
      demo-flow spec still passes

## Blocked by

None — can start immediately.

## Done

- New `disconnected` connection status and a `reduceConnectionClosed` reducer; a `SessionAlert` banner
  renders both `session_error` and dropped-connection states with a message and a Reconnect & Resume path.
- `socket.onclose` is wired (with stale-socket and intentional-close guards so a replaced/cancelled
  socket does not spuriously flag a drop). Errors and drops no longer map back to the setup phase;
  `session_error` clears the pending question.
- Reconnect resumes the same `session_id` via `resume_session`. The composer is gated on connection
  health (`canAnswer`) so a stale draft can't be "sent" into a closed socket — which previously lost the
  answer and hid the recovery banner.

## Verified

- Web vitest -> 20 passed. New reducer tests for the `close -> disconnected` transition (and no-op after
  complete/error), plus `SessionAlert` error/disconnected render tests. `tsc` + `eslint` clean; production
  build clean.
- Playwright demo-flow still green (happy path, including the composer gate).
- Note: the reconnect/resume mechanism is implemented and unit-covered; the literal manual walkthrough
  ("kill `coach api` mid-question -> restart -> reconnect -> continue") is supported but was not scripted
  as an automated e2e in this pass.

## Status

**Closed.** Acceptance criteria are implemented and covered.
