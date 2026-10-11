# Official Court-Time Grid Evidence Supplement

## Evidence source and handling

- The locally available ignored `req/1.js` bundle has SHA-256 `d0709c88bb7fb7e156a023cb32b0938253aea84f108fbf3dfc499b846813411e`. Its release/build identity is not established.
- The current local `req/` has 120 HTTP text captures. An uploaded `req.zip` was not found in the project root, Downloads, or the V1.3 worktree, so a byte-for-byte ZIP comparison is unavailable. The current local capture set and any previously uploaded ZIP are kept as separate evidence sources.
- Capture pairing and response-shape counts were computed locally in memory. This report omits filenames, request/response text, scalar identifiers, dates, prices, headers, tokens, cookies, and personal data. Opaque `item` values were not decrypted. `.env` was not read and no live request was sent.

## Directly supported official grid behavior

`bookingByTime` renders `nodeList` order as court columns and `timeList` order as rows. `stepnumber` supplies the row count. The client initializes a two-dimensional display/selection matrix in memory; it does not persist that matrix as a plan.

The official client’s display states map as follows:

| Client state | Source behavior | Use in the new preference UI |
|---|---|---|
| 1 | `unselected-grid`; this is the only state accepted by the selection branch. | Selectable only in a source explicitly identified as current or synthetic. |
| 2 | `selected-grid`; clicking toggles it back to state 1. | Local selection overlay. |
| 3 | `bought-grid`; a two-component conflict entry maps to this state. | Display as booked/occupied. |
| `course0`–`course6` | A conflict entry with a third component becomes `course{value}`. The template maps these to category styles for other, sports, project, training, art, union, and other. The click handler blocks these states. | Display as non-selectable category occupancy. Exact server-side category meaning remains unverified. |
| `course7` | The client uses this outside its displayed booking-time bounds and shows “不可预订” when clicked. | Display as non-selectable. This is client behavior, not an independent guarantee about upstream inventory. |
| Missing/error/unrecognized | Failed reads do not provide a reliable selectable grid; unrecognized course values have no reliable category mapping. | Keep as unknown and disable selection. |

The selection handler requires adjacent time-row indices, starts with minimum/maximum selected-atom defaults, applies response-provided limits when present, and checks the number of distinct court columns against `maxAppointmentNodeNum`. A selection change calls `getPayPrice`; successful quote state is separate from the grid. The plan UI in this application does not call `getPayPrice`, `createBookingBytime`, or a payment flow.

The two successful captures include the dynamic selection-limit fields as strings, but their values are intentionally omitted. The synthetic preference grid does not copy those response-specific limits. It instead requires a contiguous block equal to the current plan duration and, when multiple courts are chosen, the same complete block on each court. This keeps the stored time preference × court preference set identical to the selected grid rectangle.

The response `timeList.status` has two observed string values in the two successful samples. The compiled client renders court cells on one status branch and renders only a differently styled time heading on the other. That proves display gating only; it does not establish the complete business meaning of either value. Other values remain unknown.

## Current local capture observations

- 60 request/response pairs were matched using local capture grouping without exposing pair identifiers.
- Six pairs use the `bookingByTime` operation; two successful response envelopes have grid data. Both have ten court entries; the time rows number fourteen and twelve. Their conflict lists have 145 and 94 entries; the first response has 19 repeated court/time positions and the second has none. The corresponding price lists have 130 and 100 entries.
- Four `createBookingBytime` request/response pairs are present in the current local set. One application-level response reports success and three report failure, despite successful HTTP transport. Their opaque request bodies were not opened or used to infer fields.
- The earlier V1.3 evidence note said no direct `createBookingBytime` request was found in the reviewed corpus. The current local corpus contradicts that statement. Because the earlier corpus has no recorded digest and the referenced ZIP is unavailable, it is unknown whether the local capture set changed or the earlier matching missed these pairs. This note supersedes that earlier claim only for the current local capture set.
- Captured availability item shapes include `nodeList` labels and identifiers, `timeList` time/status fields, conflict strings, and price entries with `x`, `y`, and `price` fields. These observations do not establish a confirmed venue-to-query mapping, court ownership, price unit/currency, or live-data freshness.

## Plan and runtime boundary

- `backend/legacy_app.py` is an old single-user file/flow adapter that imports the legacy flow and is disabled by default. Its use of a Token and the legacy availability Boolean are not part of the modern multi-user feature.
- The modern app uses the Vue `PlanForm`, authenticated Flask APIs, `PlanService`, immutable `PlanRevision`, and strict `parse_manual_intent`. No migration or plan schema expansion was added.
- The new grid endpoint uses a deterministic synthetic source in development. It never reads `req/`, never writes SQLite, and never returns upstream identifiers or coordinates.
- Grid state and cell positions exist only in the preview. After a user confirms the preview, the form replaces its time preference with the selected start and its court preference with the selected manual labels. It stores no cell indices, `coordinatesList`, availability, or price. A second explicit save action is required to create a PlanRevision.
- Production disables the synthetic grid. `unbound_draft / unverified_manual` remains in force; no live availability adapter, venue binding, job, booking, quote request, or payment action was added.
