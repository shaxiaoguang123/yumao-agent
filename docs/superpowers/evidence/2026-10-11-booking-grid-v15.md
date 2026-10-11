# Booking grid V1.5 protocol and implementation evidence

## Evidence source and safe handling

- The ignored local `req/1.js` SHA-256 remains `d0709c88bb7fb7e156a023cb32b0938253aea84f108fbf3dfc499b846813411e`.
- The current local `req/` contains 120 text captures. No `req.zip` was found at the project root, Downloads, or the V1.3 worktree, so a capture-corpus comparison to the earlier ZIP is unavailable.
- Capture analysis ran locally in the existing Conda `test` environment. Only schemas, bounded counts, status categories, and adapter acceptance counts were printed. No filenames, raw bodies, display names, IDs, prices, dates, headers, tokens, cookies, order values, or opaque `item` fields were emitted or committed. `.env` was not read and no live upstream call was sent.

## Directly supported official-client display behavior

- `bookingByTime` consumes a successful response's `nodeList` in array order as court columns, `timeList` in array order as time rows, and `stepnumber` as the row count. Two unique successful local response payloads were parsed by the strict history adapter: both have ten `nodeList` entries; their `timeList`/`stepnumber` lengths are 12 and 14. Court entries contain `nodeid` and `sitename`; time entries contain `time` and `status`; `priceList` entries contain `x`, `y`, and `price` as strings in these samples.
- Official `GetSite` splits each `conflictList` string on `-`. Its first component indexes the court column, the second indexes the time row, and an optional third component selects the displayed `course` state. A two-component entry is shown as bought/reserved; `course0`–`course6` use activity category styles; `course7` is treated as non-bookable. These are client display rules, not authoritative current inventory semantics.
- Both sampled `timeList.time` values are formatted as `HH:MM`; no end time or atom duration is established. The only observed `timeList.status` strings are `0` and `1`, and the client uses status in its row-heading branch. Their complete business meaning remains unverified. The historical preview therefore shows a generic row marker and never uses it to enable an action.
- `handleChoose` accepts only client display-state 1, toggles state 2 back to 1, blocks booked/course states, checks adjacent row indices, and applies response selection-count and distinct-court-count limits. It calls `getPayPrice` after selection changes. `handlePrice(row, column)` compares those arguments against `priceList.x/y`; price units, currency, and scope are still unverified. The V1.5 app does not call `getPayPrice` or `createBookingBytime`.
- The current capture analysis found 19 repeated court/time coordinates in one response; all repeated coordinates had conflicting display categories. The other response had no repeated coordinates. The adapter marks conflicting duplicates unknown rather than accepting the official client's last-write behavior.
- Four local `createBookingBytime` request/response pairs were previously observed, with one application-level success and three failures. Their request bodies contain opaque `item` data; they were not decrypted, replayed, or used to infer a request contract. This does not affect the read-only history preview.

## V1.5 data and interaction boundary

- `AvailabilitySnapshot.time_bands` records the expected time axis, including missing intervals; `AvailabilitySlot.display_state` holds a non-execution display category while `status` remains the matcher's separate available/unavailable/unknown fact.
- `SyntheticAvailabilitySource` is now the only synthetic slot generator. `AvailabilityGridProjector` projects the same snapshot used by `AvailabilityMatcher`; gaps render unknown and unavailable/unknown slots remain excluded from matched combinations. The current synthetic `/plans` view requests the same explicit scenario as matching.
- The manual grid selects a full interval on one primary court, then adds same-interval alternatives in the user's explicit order. Reordering and removal are explicit. The form previews old/new dates, times, durations, court order, fallback scope, and unchanged price ceiling. Strict fallback is the default; retaining wider fallback requires an explicit choice. Only the existing save action calls `PlanService`.
- A separate development-only history endpoint turns a selected official response JSON into a read-only display DTO. It omits node IDs, coordinates, prices, and raw error text. It has no target-date context, time atoms, verified availability semantics, venue ownership, freshness deadline, matching, plan-binding, booking, payment, or job capability. Historical displayed-selectable cells remain disabled.
- Schema and migrations are unchanged. `unbound_draft / unverified_manual`, Task 0 PARTIAL, and Task 1B BLOCKED remain in force. No real platform request or database write is performed by grid projection or historical preview.

## Remaining evidence gaps

- The local capture corpus cannot be compared to the earlier uploaded ZIP from this machine; matching `req/1.js` hashes do not prove the capture sets are identical.
- There is no verified client build/capture-version association, venue-label-to-query-scope mapping, venue-to-court ownership, authoritative availability-state contract, atom/duration rule, price unit/currency/scope, or capture timestamp/freshness rule.
- The historical preview deliberately stays outside `AvailabilitySnapshot` and `AvailabilityMatcher` until those gaps are closed. It cannot be used to bind an intent or infer current/future inventory.
