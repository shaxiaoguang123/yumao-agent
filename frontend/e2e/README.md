# Synthetic browser regression

`npm ci` installs the exact Playwright version in the lockfile. The suite preserves
the original 46 browser scenarios and adds targeted F1–F7 regressions. It uses
real Vue, routing, SessionStore and HTTP client code in a real browser, with every
API response mocked. This does not replace Flask authorization or database tests.

```sh
cd frontend
npm ci
npx playwright install chromium
npm run test:e2e
```

An installed Chrome can be used without downloading another browser:

```sh
BROWSER_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run test:e2e
```

`-- --only-regressions` runs the 31 targeted scenarios. The default runs all 77.
Each scenario owns a new Context; service workers are blocked. The runner starts
its own loopback Vite on an available port, disables environment-file loading and
API proxying, and filters inherited `VITE_*` variables. Only this local HTTP origin
and its local HMR WebSocket are allowed. Unknown APIs and external requests are
blocked, recorded and fail acceptance. No Flask server, real database, credentials,
upstream data or repository Secrets are required.

All fixtures explicitly contain synthetic users, dates, credentials and invitations.
Request records contain only method, path, status and a boolean CSRF check. Password
and invitation elements are masked in PNG screenshots. Traces may contain synthetic
request data; never run this harness against real users or APIs.

Artifacts default to a new directory under the OS temporary directory. Set
`BROWSER_QA_OUTPUT` to a fresh directory outside the repository to preserve them.
An existing result file is rejected to prevent overwriting evidence. `results.json`
records checks, geometry, console messages, network failures and trace/screenshot
paths. Injected HTTP/network faults are identified separately from unexpected
failures; raw records remain available. A failed check or unexpected network/JS
error causes a nonzero exit. Delayed Mock handlers finish before Context teardown;
interception remains active during cleanup. Unexpected browser disconnections fail
the run and are recorded; there is no automatic scenario retry. The runner closes
only its own browser and Vite child. Browser processes are replaced on a fixed
schedule of 12 scenarios per batch, independent of success/failure. Every scenario
still gets a fresh Context and every failure remains fatal to acceptance.
The pinned Playwright Chromium is preferred
for reproducibility; separately installed Chrome versions can differ from the
version tested with this Playwright release.

CI adds an independent **Browser E2E** job. The existing **Backend tests** and
**Frontend tests and production build** check names remain unchanged. This browser
check is not made required by this change. Browser versions and fonts can differ
across macOS and Linux: geometry/interaction checks are automated; pixel equality
is not asserted. Screenshots still need actual visual review before UI acceptance.

## Real booking-plan integration

`npm run test:e2e:plans` starts a fresh temporary Flask application and SQLite
database, creates only synthetic users, and drives the actual `/api/plans` routes
through a real browser. The test covers create, refresh persistence, edit/version
history, cross-user isolation, distant-date non-queryability, and 320px overflow.
The isolated server rejects all upstream HTTP and non-loopback sockets; the runner
fails if any external request or browser error is observed. Set `PLAN_QA_OUTPUT` to
a new empty directory outside the repository to preserve screenshots and the
SQLite verification record. This is separate from the existing API-mocked suite.

UI redesign adds four discovery scenarios (one per viewport): local search/filter, distinct no-match state and explicit verification-record expansion. Intentional brand subtitle is checked separately from single-line navigation labels. The PR trigger includes the browser-fix base for stacked UI PRs.
