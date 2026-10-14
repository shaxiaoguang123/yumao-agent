# V1.3 Venue and Availability Evidence Gate

## Scope and safe handling

This update reuses the V1.2 offline protocol audit and checks only the remaining venue and read-only availability gaps. The ignored local capture directory was scanned in memory for the literal venue-list operation marker; no file names, request or response bodies, identifiers, headers, credentials, user values, dates, or prices were emitted. The marker was not found in the capture text files. No live request was made, no opaque request was decrypted, and no `.env` file was read.

## Evidence matrix

| Question | Status | Evidence-supported conclusion |
|---|---|---|
| User-visible venue list source | **Partial** | The bundled client calls `getSchoolSelect` and stores its result in `schoolList`; the reviewed bundle does not show that list rendered, and no matching response sample was found. |
| Venue name to parent query scope | **Partial** | A separately supplied navigation item's `id` is copied to the `bookingByTime` query's `nodeid`. The evidence does not join a user-visible venue label to that item or query scope. |
| Returned court ownership | **Missing** | `nodeList[].sitename` is rendered as a court label in the observed flow, but the samples do not establish which venue owns that list. |
| `timeList`, `conflictList`, `priceList` | **Partial / Missing** | Their top-level presence in the response is observed. Inner field contracts and meanings are not established; the old Python `not conflict && status != "1"` rule is not evidence of availability. |
| Availability state meanings | **Missing** | No confirmed mapping for available, occupied, or unknown states. Unknown values must remain unknown. |
| Time atoms and duration | **Partial** | Selected-time fields are carried separately, but atom length, continuity rules, and a complete duration contract are not confirmed. |
| Price and currency | **Missing** | Price unit, currency, and whether a price applies per atom or across a booking are not confirmed. |
| Client/capture version association | **Missing** | No build marker ties the local bundle and the observed requests/responses to one client release. |
| `appointmentType` and `booktype` | **Partial** | Static call sites show separate roles, but semantic mappings are unknown. These fields do not gate display-directory or read-only availability work; they remain relevant to any future booking execution work. |

## Implemented boundary

- `/api/plans/options` continues to return an empty catalog and now reports the catalog version, source state, evidence readiness, and disabled capabilities. It exposes no upstream identifiers.
- An immutable `VenueCatalog` data contract now separates a display-only directory from verified scope/court associations. Scope configuration references are server-side and omitted from public DTOs; the application has no configured catalog, so the contract currently publishes no entries.
- `/plans` explains why no trusted venue can be selected or bound. Existing hand-entered preferences remain unverified manual text; no binding action is exposed.
- `AvailabilitySnapshot` now has optional catalog version, capture time, and declared validity deadline fields. Historical snapshots are explicitly `historical_unverified`; the matcher can report `freshness_state` as-of a supplied timestamp without upgrading data to live or bookable status.
- `backend.tools.availability_evidence_audit` validates a small, strict, value-only evidence manifest and prints only status/readiness codes. It does not read capture files or establish that an attestation is true; evidence still needs human review.
- No runtime VenueCatalog entry, plan-binding operation, recorded-response adapter, real query, booking, payment, or job is enabled. No database migration was added.

## Minimum evidence to continue

1. Record the official client build/version for a single local session.
2. In the official client, load the venue selection screen and preserve the matching venue-list response locally. Establish which displayed label and selected item fields are passed into the parent query scope, using official source or documentation where the captured request wrapper is opaque.
3. Select one venue and target date, then preserve its matching read-only response locally. Confirm that its returned court list belongs to that venue and document the field paths and types without publishing scalar identifiers.
4. From authoritative source or explicit platform documentation, confirm available/occupied/unknown meanings, atom size and continuity, and price unit/currency/scope. Record the capture time and the source's validity/expiry behavior.
5. Keep original captures and any scope values on the local machine. Commit only the sanitized evidence-status manifest and synthetic regression fixtures.

The checker can be run with `python -m backend.tools.availability_evidence_audit --template` to obtain a safe manifest shape, then with `python -m backend.tools.availability_evidence_audit <local-sanitized-manifest.json>` to calculate readiness. A `confirmed` value is an audited human assertion, not a cryptographic proof.
