# Page-load performance — 2026-09-09

The main delays were remote database round trips, before the browser could
start displaying media.

- `db.connect()` opened and closed a physical Postgres connection for every
  operation, including user lookup, membership lookup, and each asset category.
  A fresh connection plus `SELECT 1` measured 584–757 ms from this Mac.
- `preprod.list_concepts()` queried locations separately for every concept.
  Reading 100 concepts required 101 queries even when none named a room.
- `/ui` resolved the user and memberships twice: once for the active brand,
  then again for the tenant's manual-lane visibility.
- Provider availability checks replayed account-key table and ownership setup
  on reads, once for each renderer on Queue.
- Client startup waited for capabilities before requesting the asset catalogue.
  Gallery backgrounds eagerly fetched all images, while every video requested
  metadata even when off screen.

## Changes

The web server owns a bounded Psycopg connection pool for its lifespan. CLI
and explicit alternative database/schema connections remain standalone. Pool
connections keep UTC, transaction commit/rollback, health checks, and shutdown
cleanup. User and membership results are reused only within one request; the
next request still rechecks access.

Concept lists fetch their locations in one additional query, preserving tenant
scope, alphabetical location order, and empty location lists. Saved-key reads
check for the table and fall back normally when absent; schema creation remains
on writes. No model or render approval behavior changes.

The catalogue starts loading alongside capabilities, and simultaneous catalogue
requests share one promise. Capability gating remains in place. Gallery images
use native lazy loading and asynchronous decoding; videos start loading on use.

## Measurements

Authenticated FastAPI requests from this Mac against the existing remote
Postgres, using the same user and data. Responses were all HTTP 200, with
unchanged payload sizes. These measure server response time through TestClient,
not a deployed browser's network transfer or total time to load images.

| Read route | Before connection/batch fixes | After |
| --- | ---: | ---: |
| `/api/assets` | 5.76 s | 2.68 s |
| `/api/media?kind=all` | 5.79 s | 2.97 s |
| `/api/pipeline/concepts` | 13.45 s | 3.14–3.20 s |
| `/api/queue/pending` | 23.00 s | 5.86–6.19 s |

Baseline route measurements already include the request-local auth cache.
Repeated low-level catalogue reads fell from 3.45–3.66 s to 1.75–1.85 s.
Network latency varies; production hosting near Postgres will have different
absolute timings. Queue still performs separate provider availability and daily
usage reads; the tests and live timings do not establish that all latency is gone.

## Verification and activation

Regression tests cover physical connection reuse, rollback after a failed write,
explicit database/schema isolation, permission revocation on the next request,
constant query count for concept lists, and saved-key reads in read-only
transactions. Existing auth, pre-production, Queue, and tenancy tests exercise the
surrounding behavior. A Node runtime check verifies client request deduplication,
cache refresh, and recovery after a failed fetch.

Install the updated requirements in each runtime and restart/redeploy the web
server to activate its lifespan pool. The production deployment is recorded below.

Validation results:

- All six new performance regressions pass; focused auth/database tests passed
  (87 tests before the last three regressions were added), and the full suite
  includes the final regression set.
- The 60 other tenancy tests pass. All 55 manual-lane tests pass.
- Full suite (`pytest tests/ -q -n 4`): 1,918 passed, 8 expected failures,
  59 failures and one teardown error. The 59 failures are 58 orchestrator tests
  whose existing generator mock lacks the `brain` argument, plus the existing
  `/api/brains` route audit. Representative failures from both groups reproduce
  with the pre-change database, concept, key, and auth implementations loaded
  from HEAD in memory, leaving workspace files untouched.
- The parallel teardown error was a database deadlock in a scene-pick test;
  that test passes when rerun alone alongside the six new regressions.
- Repository lint, diff whitespace checks, JS syntax checks, and the client
  loader runtime checks pass.


## Production deployment

Deployed on 2026-09-09 at 17:03 UTC to `zeropage-studio`, machine version 8.
Image: `registry.fly.io/zeropage-studio:deployment-01M23HZ6DY50ZPDTBCYGGR38A6`.

The image extends the previous live image and overlays only the ten performance
files plus Psycopg Pool 3.3.1. The patch was checked against source retrieved from
the live machine. Its existing frame-bank schema annotation was preserved;
unrelated workspace edits were not included. Deployment used a rolling update
and kept the existing one-machine configuration.

The Fly health check passes. Public `/healthz` and `/signin` return 200;
signed-out `/ui` redirects to sign-in and `/api/assets` returns 401. The four
changed JS/CSS assets served publicly match the deployment payload byte for byte.

Authenticated HTTP checks against the running production server returned 200:

| Route | Server-side elapsed time |
| --- | ---: |
| `/ui` | 60 ms |
| `/api/assets` | 168 ms |
| `/api/media?kind=all` | 146 ms |
| `/api/pipeline/concepts` | 237 ms |
| `/api/queue/pending` | 270 ms |

These requests originated inside the Fly machine, so the timings include live
application/database work but exclude the visitor's network and image loading.
No generation or render was requested during verification.

Previous image retained for rollback:
`registry.fly.io/zeropage-studio:deployment-01M222MJG7RRC5D8ZJDG183F7V`.

## Assets 500 follow-up — 2026-09-09

The initial production smoke check was sequential and missed a concurrency bug.
Live logs showed `/api/assets` returning `DeadlockDetected` in
`render_assets.list_all -> init -> db.own_table -> backfill_owner`. Assets and
Media GETs both replayed schema/index setup and ownership updates, then deadlocked
while acquiring stronger locks on `generated_assets`.

`render_assets.list_all` now only checks whether the table exists and selects
this account's rows; it returns an empty list before first initialization.
Startup and writes retain initialization. Regression tests first reproduced the
write-on-read error in a read-only transaction, then passed with the fix. A test
of 24 overlapping Assets/Media requests with six workers and a four-connection
pool also passes. All nine concurrency/performance tests and relevant lint pass;
the preceding API run's other 58 tests passed.

Deployed only `src/render_assets.py` over the previous live image:
`registry.fly.io/zeropage-studio:deployment-01M23JD7J27X3RT0YA2713Y0NA`.
Fly health checks pass. A live test of 40 authenticated Assets/Media requests with
six concurrent workers returned 40 HTTP 200 responses. Assets median/max:
163.5/220 ms; Media median/max: 145/239 ms, measured inside the Fly machine.
Public health/sign-in checks and signed-out asset access checks also pass.
