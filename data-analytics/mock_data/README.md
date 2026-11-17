# dynamo/perf-n-plus-one-repair

**Category:** Debugging and Repair -- Performance Debugging

## What this task is

A Flask + SQLAlchemy web app has a severe performance regression: response
times under moderate concurrent load have degraded from well under 10ms to
over 2 seconds. The agent must profile the live app, diagnose the true
root cause, and fix it.

## Why it's hard

The N+1 query is buried three call-chain levels deep behind ORM
lazy-loading (endpoint -> controller -> service -> per-order
serialization loop). A decoy function with a real but fixed, non-scaling
CPU cost shows up as the single largest self-time entry in a naive
profile read, tempting the wrong fix. The actual regression's cost is
spread thin across hundreds of cheap individual queries in the framework
layer, visible only via cumulative time and call counts, not self-time.

## Verification

The agent must name the exact fully-qualified function it fixed in
`/app/results/diagnosis.json` (exact string match) *and* the live app must
independently measure at or below the pass threshold under a fixed load
protocol (8 rounds of 20-concurrent requests, 3 discarded as warmup,
median of the remaining 5 rounds' medians). Neither the diagnosis nor the
timing alone is sufficient -- both must be correct.

**Note on the pass threshold:** the original proposal specified 50ms.
Empirical calibration during build found that framework-level overhead
(SQLAlchemy session/query-compilation cost) under 20-way concurrency
makes 50ms unreliable even for a genuinely correct fix -- this was
confirmed by isolating the overhead experimentally, independent of the
N+1 bug itself. The threshold was raised to 100ms, which still preserves
a 20x+ multiplicative gap over the ~2.3-2.9s broken baseline measured
under the identical protocol.

## Running locally

```
harbor run -p . --agent oracle   # reward 1.0
harbor run -p . --agent nop      # reward 0.0
```
