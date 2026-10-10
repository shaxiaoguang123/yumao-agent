# Availability Matcher MVP (V1.2)

## Normalized input and matching

`AvailabilitySnapshot` is immutable: one target date/IANA timezone, venue display
name/optional semantic key, source, explicit simulation boolean, optional currency
code/minor-unit exponent, and immutable `AvailabilitySlot` atoms. Each atom has a
court name, local `HH:MM` start/end, status `available/unavailable/unknown`, and optional
nonnegative exact-integer price for the WHOLE atom. End `24:00` is supported. There
are no platform IDs, coordinates, credentials, payment or availability status-code
assumptions. Snapshot limits: 2048 atoms and 32 courts. Overlap/duplicates/invalid
values are rejected. Local-clock days with DST gaps/folds/offset changes are rejected;
an offset-aware contract must precede support for those days.

`AvailabilityMatcher.match(saved_plan, snapshot)` has no I/O or persistence. It
validates the manual intent contract, requires equal date/timezone/venue display scope,
then searches each permitted court at explicit preferred starts and (only if authorized)
slot boundaries inside the inclusive allowed-start range. Atoms are indivisible; both
candidate boundaries must align with atom boundaries. Whole, contiguous atoms must
cover exactly `duration_minutes` on the same court and be explicitly available. Missing
intervals are gaps, unknown status is not availability; no optimistic interpretation.

Deterministic ascending ranking tuple:

1. Explicit start-time index; all exact preferences precede all shifted starts.
2. Explicit court index; authorized other courts follow all listed courts.
3. Absolute shift distance to nearest preferred start (zero for exact starts).
4. Nearest preferred-time index (break equal-distance ties).
5. Start minute, then court name in Unicode order.

Prices are a filter, not a ranking factor. Add whole-atom prices only with complete
currency metadata and all prices known, with safe JS integer bounds. Budget comparison
requires exact equality of currency code AND minor-unit exponent with the saved plan.
Missing prices/currency or incompatible units never pass a price ceiling; absent ceiling
may retain a candidate with price unconfirmed, never invented zero. Results include
rank, interval, duration, total price when confirmed, reasons, specific fallback flags,
provenance/trust and no execution rights. Lower-priority explicit times/courts are shown
as backups, separately from use of authorized other courts/time shifts.

Rejections distinguish date/timezone/venue scope, court/time authorization, unavailable,
unknown, gaps, budget, currency mismatch and missing prices. Summaries count every
rejection; detail is capped at 128, candidates at 256 (after full sorting), with explicit
truncation flags and full candidate count. Identical input/order-insensitive slot data
produce identical results.

## Synthetic source and API

`SyntheticAvailabilitySource` uses reproducible 30-minute templates: complete,
partially occupied, time gap, none available, high price, missing price. Date/timezone and
manual venue/court labels are copied from the saved plan purely to instantiate a
simulation. Extra court labels explicitly say simulation. This does not confirm venue
identity/court membership, add catalog entries or create upstream identifiers. Price
fixtures use CNY exponent 2, independent of deployment currency.

- `GET /api/availability/simulation/options`: Session, enabled flag, scene descriptions.
- `POST /api/availability/simulation/plans/<plan_id>`: Session+CSRF; exact body
  `{base_version,scenario}`, max 16 KiB. POST performs a read-only computation.

Only PlanService's owned saved current version is used; clients cannot submit inventory,
intent fields, IDs or execution parameters. Source/matcher receive data only after tenant
and version checks. Recheck version after computation and return 409 on change; result
records the version it matched. No plan/revision/job writes, Provider or booking HTTP.

Disabled by default. Explicit `APP_ENV=development` AND
`AVAILABILITY_SIMULATION_ENABLED=true` enable simulation. Production always disables
it even if the flag is true. Disabled options contain no scenarios; matching returns
`simulation_not_enabled`. Schema remains 6; all migrations unchanged.

## UI and verification

`/plans`: a separate panel selects a saved plan and scenario, explicitly triggers matching,
and lists candidates with reasons, backup use, prices and empty-result diagnostics.
Prominent simulation warning, no execution actions. Results are cleared/fenced on
account/CSRF/plan-version/scenario changes; network errors preserve selection, and 409
asks the user to refresh saved plans. Manual/AI editors are retained.

Unit tests cover ranking, continuity, authorization, unknowns, prices/currency, snapshot
validation, cross-user access, read-only persistence, disabled production and concurrent
version changes. `npm run test:e2e:availability` uses fresh Flask/SQLite, Fake Planning
Provider and denied external requests: natural-language proposal → confirmation → saved
plan → preferred/backup/gap/no-result/budget/missing-price/mobile/isolation scenarios.
Codex browser acceptance uses desktop 1440 and phone 390 with real screenshots.

## Future real data boundary

The pure matcher accepts normalized non-simulated snapshots without changing ranking or
coverage logic, but never marks them trusted/executable by itself. Before a real adapter,
obtain reviewed venue list/query-parent mapping, court ownership, same-build protocol
evidence, actual availability-state meanings, bookable atom/duration rules and per-atom
price/currency semantics. Adapter scope must be explicitly bound to a trusted catalog;
manual-name equality alone cannot grant real inventory or booking rights. No reuse of
legacy `backend/availability.py` status assumptions. Snapshot freshness/version policy
and user authorization for real querying remain future work. Task 0 PARTIAL and Task
1B BLOCKED remain; all plans stay `unbound_draft / unverified_manual`.
