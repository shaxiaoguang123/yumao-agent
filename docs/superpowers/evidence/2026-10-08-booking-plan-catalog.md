# Booking Plan Catalog Evidence

> **Task 0 status: PARTIAL — Task 1 catalog implementation is blocked.**
>
> This public-safe note records evidence and limits. It does not publish upstream query identifiers or authorize any real query or booking.

## Audit scope and handling

- Audit date: 2026-10-09.
- Repository revision inspected: `feature/03-reservation-intent` at `5e7c3a0acefd39f6a3af2a8d5dfed1e8e615015c`, which includes `origin/main` at `2ca7d2b3ba83fa218dc0924433e05c25e7a8e87b`.
- Primary evidence: the local frontend bundle `req/1.js` and the ignored local capture corpus under `req/`. The capture filenames and all captured scalar values are intentionally omitted from this public document.
- Scope reviewed: two locally paired `bookingByTime` request/response samples, the request-building and response-consumption paths in the frontend bundle, and the frontend navigation/selection paths that feed them. Pairing was checked locally by matching request/response capture basenames; the two response samples both had a successful envelope and a `resultData.nodeList`.
- The source locations below refer to `req/1.js` in the primary checkout. It is a bundled client artifact; its exact release/build identity and capture date are not independently verified.
- The architecture spec and old Python code were treated as requirements/context only, not as upstream protocol evidence. No `DEFAULT_NODEID` inference was used.
- All capture analysis ran offline in the existing Conda `test` environment. The local parser emitted only allow-listed field names, route classes, types, counts, and equality/shape checks. It did not emit request/response text, identifier values, header values, credential values, user data, dates, prices, or order data. The opaque request wrapper was not decrypted, and `.env` was not read. No live upstream request was sent.

## Findings

| Finding | Evidence and observation | Status | Catalog consequence |
|---|---|---|---|
| Parent venue query scope | In the booking page (`req/1.js:98`), the page receives a `nodeid` from its navigation item; the query builder assigns that value to the request object's top-level `nodeid` before calling the `bookingByTime` operation. This is the role represented by `venue_query_nodeid` in the application plan. The captured request body contains only an opaque `item` wrapper, so its scalar value is not available for a safe semantic mapping. | **PARTIAL** — request role is confirmed; venue identity/mapping is not. | Do not create a selectable venue or publish its query identifier. |
| Court-level identifier | Each response sample has a `resultData.nodeList` array. Each of its 10 entries has a string `nodeid`; the values are distinct within each response. The response has no parent query `nodeid`. The query builder and response parser therefore use `nodeid` at different structural levels: one selects a query scope, while each `nodeList` item describes a returned court. The samples do not prove global uniqueness or a numeric inequality between parent and child identifiers. | **CONFIRMED** for the structural distinction; universal identity properties are **UNKNOWN**. | Never use a court `nodeList[].nodeid` as the venue query scope or persist it as future availability/execution state. |
| Court display label | Each sample has 10 string `sitename` values, unique within the sample and equal across the two observed samples: `1号场` through `10号场`. The frontend assigns the returned `nodeList` to its court array and renders each item's `sitename` as the visible label (`req/1.js:98`). | **CONFIRMED** as the observed response-to-UI label path; applicability beyond these samples is **UNKNOWN**. | These are observed labels only. They are not yet approved as catalog keys because no venue has been established for them. |
| Venue selection and name | The home component stores the dynamic `getschoolList` response in `schoolList` (`req/1.js:350`). Separately, a detail-page item carries `nodeid` and `nodename` and is passed to the `bookingByTime` page (`req/1.js:48,98`). The reviewed source does not prove that `schoolList` supplies that item, and no response sample matching `getschoolList` could be identified. The booking page's `venueName` literal is a placeholder, not a venue label. The available evidence does not join a user-visible venue name to the query-scope identifier or to the two court-list samples. | **UNKNOWN**. | No venue option, venue key, or venue-to-court relationship may be published. Do not use `nodename` or the placeholder as a substitute mapping. |
| Dynamic response data | The observed response carries `nodeList`, `timeList`, `conflictList`, and `priceList`; the page also consumes response-derived booking-window fields. These are read from the current response to render that page. Only `sitename` is used here as an observed semantic display label. | **CONFIRMED** as response-derived data; future values are **UNKNOWN**. | Do not treat response order, court identifiers, time arrays/indices, coordinates, conflicts, prices, opening times, or availability as stable catalog facts. |
| `appointmentType` | In the frontend's price-query builder (`req/1.js:98`), `appointmentType` is a separately assigned string-valued field on the `getPayPrice` request object. The corresponding captured request uses an opaque `item` wrapper, so the plaintext field/value was not independently verified from the wire body. | **PARTIAL** — source assignment and request role are visible; semantic mapping is not established by the capture. | Do not expose it as a user-selectable booking type yet. |
| `booktype` | The booking page assigns a numeric literal to `booktype` in its booking request object (`req/1.js:98`). The payment component reads `booktype` to dispatch among different booking flows (`req/1.js:146`). No direct `createBookingBytime` POST request record could be identified in the reviewed capture corpus; the `booktype` fields in other captured JSON were not mapped to this request. | **PARTIAL** — source shows a separate booking-flow/category field, but the captured wire contract and approved semantic mapping are unresolved. | Do not equate `booktype` with `appointmentType`, and do not publish any code value. |
| Duration | The frontend carries the selected time data separately: the selected array is sent as `reserveTime` in the price-query object and as `coordinatesList` in the booking object; `timeList` is also passed separately (`req/1.js:98`). No reviewed evidence establishes a duration mapping from either type field. | **PARTIAL** — duration is represented separately from the booking-flow field, but a complete duration contract is not established here. | No duration may be inferred from `booktype` or `appointmentType`; in particular, no “two-hour” meaning is asserted for any code. |

## VenueCatalog decision and version policy

- A single time-slot query flow is visible in the official frontend and in the matched `bookingByTime` samples. This confirms a query flow, not an executable `booking_type` semantic mapping.
- The court labels `1号场` through `10号场` are observed, but cannot be attached to a confirmed venue. The venue-list response and the parent-scope-to-venue mapping are missing.
- **No runtime catalog version or selectable VenueCatalog entry is authorized by this audit.** In particular, no `venue_key`, `court_key`, `booking_type`, or upstream identifier is approved for Task 1.
- Once the missing evidence is obtained and reviewed, the first server-side catalog can receive an explicit version. Exact query identifiers must remain only in the approved server-side catalog source; they must not appear in this evidence file, client options, fixtures, or logs. Catalog changes must create a new version and must not reinterpret labels or choices already snapshotted by a `PlanRevision`.
- Any future catalog remains a semantic user-selection aid. It cannot establish that a court appears in a future target-date response or that it is available.

## Unresolved evidence and blocking impact

1. Obtain or locate an official/local response for `getschoolList` that can be safely reduced to venue labels and parent-scope roles. No such response could be identified in the reviewed capture set.
2. Establish a reviewed, local-only mapping from a user-visible venue choice to the `bookingByTime` request's parent `nodeid`, without publishing the identifier. The existing request wrapper is opaque; do not read `.env` or expose/decrypt its contents to satisfy this note.
3. Establish which observed `nodeList[].sitename` labels belong to that confirmed venue. The two current samples alone do not establish a reusable venue-to-court catalog.
4. Obtain safe evidence for the semantic mapping of `appointmentType` and `booktype`, including the relationship (if any) between price-query and booking flows. The captured `getPayPrice` bodies expose only an opaque wrapper, and no direct `createBookingBytime` POST record was identified.
5. Keep duration semantics separate. A future duration contract must be grounded in the selected time-list behavior, not inferred from either type field.

Until these items are resolved, the affected venue/court/type options remain blocked and Task 1 must not begin from guessed or legacy identifiers.

## Task 1 recommendation

**Do not start Task 1 yet.** The application may implement a versioned, server-only catalog after the venue list, parent query scope, court-label ownership, and one supported booking-type mapping are confirmed. Until then, keep all observed labels as evidence only; do not add a synthetic runtime catalog entry to production code or tests. Task 1's catalog tests may use synthetic values only after the approved semantic contract is recorded.

## Task 0 checklist

- [x] Read only local frontend source and local captures; no live request.
- [x] Record the request-scope versus response-court identifier roles without recording identifier values.
- [x] Trace `sitename` from the response to the visible court label.
- [x] Compare `appointmentType` and `booktype` independently; do not infer duration from either.
- [x] Record capture/sample scope and source locations without copying capture contents or private filenames.
- [x] Keep user dates, prices, identity values, Tokens, request/response bodies, and upstream identifiers out of this file.
- [ ] Confirm the venue list and venue-to-query-scope mapping.
- [ ] Confirm a venue-to-court catalog mapping.
- [ ] Confirm an approved booking-type mapping and its captured wire contract.
- [ ] Approve any runtime catalog version.

**Outcome:** Task 0 is **PARTIAL**. The evidence is sufficient to describe the query/court response structure and the observed court-label rendering path, but insufficient to authorize a venue catalog or booking-type option. Task 1 remains blocked.
