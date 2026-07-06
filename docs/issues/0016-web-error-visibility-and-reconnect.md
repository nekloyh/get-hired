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

- [ ] Starting live mode without a configured provider shows the server's error message in the UI
      instead of silently resetting to setup
- [ ] A mid-Session `session_error` keeps a visible error with the message text; the Candidate is
      told what happened and what to do next
- [ ] WebSocket close is handled: the UI enters a distinct disconnected state and offers
      reconnect/resume; reconnecting resumes the same `session_id`
- [ ] Demoable: kill `coach api` mid-question, restart it, reconnect from the browser, continue
      the Session to completion
- [ ] Component tests cover the error render and the close→disconnected transition; the Playwright
      demo-flow spec still passes

## Blocked by

None — can start immediately.

## Status

**Open.**
