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

`-- --only-regressions` skips the original baseline and runs the regression and feature suites.
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

## Real planning integration

`npm run test:e2e:planning` drives the current chat-based Agent workflow against a
temporary Flask application and SQLite database with a fake model provider. The
availability integration uses synthetic data. These checks cover the current plan
creation path; they do not contact the upstream booking service or make payments.
The retired one-shot plan editor E2E was removed because that UI was replaced by
the conversational Agent flow.

UI redesign adds four discovery scenarios (one per viewport): local search/filter, distinct no-match state and explicit verification-record expansion. Intentional brand subtitle is checked separately from single-line navigation labels. The PR trigger includes the browser-fix base for stacked UI PRs.

## Compact responsive layout

The responsive suite covers 320–1920px widths and a short desktop viewport. It checks the visible Agent preview, first-screen phone input, execution-help bounds, both navigation rows after resizing, dense log details, and inline model editing. API responses stay synthetic and blocked from the upstream service. Screenshots support manual visual review; these checks do not establish physical iOS keyboard or safe-area behavior.

## System light and dark themes

The application follows `prefers-color-scheme` through CSS, including native
controls and browser theme metadata. No account preference or JavaScript theme
state is stored. Theme scenarios run with the full suite; use
`npm run test:e2e -- --only-themes` for a focused check.
They cover public and authenticated routes at 390px and 1440px, a live system
preference change without losing form input, text contrast, focus feedback,
popovers, official price cells and layout overflow. The official venue palette
and its dark price text are preserved separately from the application theme;
these fixed upstream colors are checked for consistency, not claimed to pass
the general 4.5:1 text-contrast check. All API responses remain synthetic.
