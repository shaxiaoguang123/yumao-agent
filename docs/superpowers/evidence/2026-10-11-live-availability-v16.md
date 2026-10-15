# V1.6 booking-node, availability-display, and venue evidence update

## Scope and handling

- Updated 2026-10-15 with the client display/selection rules below.
- Reviewed the local official frontend bundle `req/1.js` from the primary checkout (SHA-256 `d0709c88bb7fb7e156a023cb32b0938253aea84f108fbf3dfc499b846813411e`), one captured fingerprinted `bookingnode` static asset, its nearby `getBookingNode` request/response pair, and the existing `bookingByTime` source path. The repository marks `req/` as reference-only; the bundle's exact release association is unknown.
- The local audit utility verifies only source markers, expected routes, response shape, same host/User-Agent digest, and capture sequence proximity. Its report emits a count and field roles only. It does not emit capture names, venue labels, identifiers, header values, response bodies, profile data, or opaque `item` values.
- No `.env` was read, no opaque item was decrypted, and no request was sent. The audit was run only against existing local captures.

## Confirmed booking-node flow

- The `getBookingNode` response's `resultData` list is assigned to the official page's `links`; the page renders `nodename`.
- Clicking an item passes its `id` and `nodename` through the navigation item. The next page assigns `item.id` to `param.nodeid`; the time-booking page uses that node ID as the top-level `bookingByTime` query scope.
- One successful local `getBookingNode` response had four unique items with string `id` and `nodename` fields. The capture and fingerprinted source asset share host and User-Agent metadata and occur close together in the local sequence. The exact app release/build association is still unknown; the asset fingerprint does not establish an app release version.
- `getSchoolSelect` assigns data to `schoolList`, but the reviewed bundle does not establish a user-visible render/selection path from `schoolList`.

## Confirmed client-side availability display rules

The reviewed bundle confirms how this client renders and handles `bookingByTime.resultData.conflictList`:

- A two-part marker uses `[court index, row index]` and sets that cell to client state `3` (`bought-grid`); the click handler does not allow that cell to be selected.
- A three-part marker uses `[court index, row index, category code]` and sets the cell to `course<category code>`. Codes 1–5 render as 体育课、项目培训、体训队、艺术团、工会活动; codes 0 and 6 render as 其他活动; code 7 renders as 不可预订. The click handler rejects codes 0–6 and shows an unavailable message for code 7.
- Unmarked cells start in client state `1`, which can enter the selection handler only while the applicable `bookingstarttime`/`bookingendtime` window is open.
- Before that window, the client may initialize the whole grid to `course7`; `GetSite` then overlays the specific cells in `conflictList`. Therefore a gray pre-opening cell is not enough to conclude that its raw upstream state is a permanent `不可预订` marker. The 00:30 preflight design must distinguish the global client-side time gate from explicit conflict markers, then obtain a fresh response before composing the final request after opening.

These are confirmed **client display and selection rules**, not proof that an unmarked cell will accept an order or that the booking endpoint will succeed. `timeList.status` semantics, response freshness/authorization, venue and court ownership, price meaning, and exact time-atom continuity remain separate evidence questions. The mapping can support conservative candidate pruning, but it does not enable `recorded_availability`, live querying, or booking in this branch.

## Why this does not establish a physical VenueCatalog

The captured `getBookingNode` list contains a booking-category label (“羽毛球”), not a physical venue name. The source confirms that its ID is a query-scope node; it does not prove that this node label represents a physical venue or that prior `bookingByTime` court samples belong to it. The historical `bookingByTime` request body remains opaque, so it cannot correlate those sample courts to the selected node. The imported list must not be published as a trusted physical VenueCatalog.

## Readiness

- Confirmed: `getBookingNode.resultData` has a user-visible option path; selected `id` flows to the `bookingByTime` `nodeid` field.
- Missing: a user-visible physical venue/campus name tied to that query scope; a same-flow `bookingByTime` request/response association for the selected physical venue; court ownership for the returned `nodeList`.
- Confirmed at the client-UI layer: conflict marker coordinates/category-code mapping, visible activity labels, unmarked-cell selection gate, and the distinction between explicit markers and the pre-opening whole-grid gray state.
- Still unverified: authoritative inventory meaning and reservation success, `timeList.status` semantics, price unit/currency/scope, time atom and duration continuity, capture freshness, same-flow physical venue/court ownership, and a release-level client version.
- Therefore the trusted physical VenueCatalog stays empty; plan binding, real AvailabilitySnapshot creation, matching from captured data, and live read-only queries remain disabled. The existing historical adapter remains a read-only display projection. No migration was added.

## Minimal next capture

In the official client, select the observed booking category, then continue until the UI actually identifies a physical venue/campus and displays that venue's court-time page. Capture, in one local trace:

1. The user-visible physical venue choice and its response/source path.
2. The selection handoff showing its `id` becoming the subsequent `bookingByTime` scope, before request wrapping/encryption if available through normal client debugging.
3. The corresponding successful `bookingByTime` response and its capture timestamp/client asset fingerprint.

Keep request headers and credentials local. Do not send a Token, cookie, or payment data in chat. One read-only bookingByTime request may be made by the official client when you choose; this development did not issue it.

## Local audit command

Use the existing Conda `test` environment and pass the four matching request/response capture files plus the local `req/1.js` source. The command prints only a sanitized field-flow/readiness report; it does not write a catalog or contact the platform. Keep the capture paths and files local.

```bash
python -m backend.tools.booking_node_evidence_audit \
  --asset-request "<local bookingnode asset request capture>" \
  --asset-response "<local bookingnode asset response capture>" \
  --node-request "<local getBookingNode request capture>" \
  --node-response "<local getBookingNode response capture>" \
  --booking-source "<local req/1.js path>"
```
