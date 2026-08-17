# How a test run actually runs

The play button in the Tests tab, the `run_component_tests` MCP tool and
`aw-workspace-cli architecture run` all end up in the same place. What differs
is who waits.

## The route returns a job, not a result

`POST /testcases/run {"file_path": …}` returns immediately:

```json
{"id": "run-b78605b755fa", "file_path": "…", "status": "queued",
 "started_at": 1755…, "finished_at": null, "result": null, "error": null}
```

Poll `GET /testcases/jobs/{id}` until `status == "done"`, then read `result`
(the runner's verdict) or `error` (the run itself blew up — not a test
failure). `GET /testcases/jobs` lists every job this process still knows
about, newest first, so a UI that lost its id to a page reload finds the run
again instead of starting a second one.

Pass `{"wait": true}` to block and get the result inline. The CLI does exactly
that: it talks over loopback, where there is no edge timeout, and a script that
has to poll for its own exit code is worse than one that waits.

## Why it isn't synchronous

It was, and three things followed from that. None of them looked like what
they were.

**The tunnel edge cuts requests at ~30s.** Any suite slower than that came back
to the browser as `502 workspace offline` — the same thing a genuinely dead
workspace produces. The UI could not tell a slow pass from an outage, so the
best it could honestly say was "unknown, refresh to see the recorded status".
The test had usually passed.

**A Starlette threadpool worker was held for the whole run.** That pool is
shared with every route in the workspace, and these are multi-minute pytest
runs. Blocking it is not the same as blocking the event loop — the workspace
stayed responsive — but it is a real bite out of a shared resource for no
reason.

**Nothing bounded concurrency.** `run_component_tests` loops over every test
linked to a component. A component with 77 of them forked 77 pytest processes
back to back with no ceiling. On 2026-08-16 a sweep of ~37 suites coincided
with the workspace going unreachable for about 90 seconds. That cause was never
proven and is not claimed here — but an unbounded number of heavy subprocesses
is worth removing either way.

`jobs.MAX_CONCURRENT` (2) is the ceiling now. Two rather than one so a slow
suite doesn't stall an unrelated quick check, and not more because these share
the workspace's CPU with everything else it does.

## Two details that are easy to get wrong

**The semaphore is acquired inside the worker thread, not in `start()`.** Taking
it in the caller would make `start()` block precisely when both slots are busy —
the one case where the caller most needs its id back. A `queued` job is honest
about waiting; a hung POST is not.

**Job state is in-process and deliberately not persisted.** A job is a few
minutes of liveness, and a workspace restart kills whatever was running, so a
`running` row in a table would outlive the thing it describes and there would be
nobody left to correct it. The durable record is `last_run_status` on the
testcase, written by the runner exactly as before — a job is how you watch a
run, not where its outcome lives.

## What the runner does with the file

Three levels, first match wins:

1. the testcase's own `run_command` (set via `set_testcase_run_command`),
2. the component's `test_cmd`, with `{file}` / `{rel}` substituted,
3. a naive `pytest <file>`.

A `run_command` beginning with `SKIP:` marks a test that cannot run in this
workspace (a Watch e2e needing a simulator, a Swift suite, a browser e2e). It
records as skipped with the reason, rather than being deleted from the catalog
to make a dashboard green — a test that exists and can't run here is a fact
worth keeping.

Exit codes are classified, not truthed: pytest's 2 / 4 / 5 mean *no verdict was
produced* (collection error, usage error, nothing collected), which is not the
same as a failing test and must not be recorded as one.
