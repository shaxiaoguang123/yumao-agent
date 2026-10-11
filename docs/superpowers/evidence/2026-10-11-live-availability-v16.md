# V1.6 booking-node and venue evidence update

## Scope and handling

- Reviewed the local official frontend bundle `req/1.js` (its previously recorded SHA-256 is unchanged), one captured fingerprinted `bookingnode` static asset, its nearby `getBookingNode` request/response pair, and the existing `bookingByTime` source path.
- The local audit utility verifies only source markers, expected routes, response shape, same host/User-Agent digest, and capture sequence proximity. Its report emits a count and field roles only. It does not emit capture names, venue labels, identifiers, header values, response bodies, profile data, or opaque `item` values.
- No `.env` was read, no opaque item was decrypted, and no request was sent. The audit was run only against existing local captures.

## Confirmed booking-node flow

- The `getBookingNode` response's `resultData` list is assigned to the official page's `links`; the page renders `nodename`.
- Clicking an item passes its `id` and `nodename` through the navigation item. The next page assigns `item.id` to `param.nodeid`; the time-booking page uses that node ID as the top-level `bookingByTime` query scope.
- One successful local `getBookingNode` response had four unique items with string `id` and `nodename` fields. The capture and fingerprinted source asset share host and User-Agent metadata and occur close together in the local sequence. The exact app release/build association is still unknown; the asset fingerprint does not establish an app release version.
- `getSchoolSelect` assigns data to `schoolList`, but the reviewed bundle does not establish a user-visible render/selection path from `schoolList`.

## Why this does not establish a physical VenueCatalog

The captured `getBookingNode` list contains a booking-category label (“羽毛球”), not a physical venue name. The source confirms that its ID is a query-scope node; it does not prove that this node label represents a physical venue or that prior `bookingByTime` court samples belong to it. The historical `bookingByTime` request body remains opaque, so it cannot correlate those sample courts to the selected node. The imported list must not be published as a trusted physical VenueCatalog.

## Readiness

- Confirmed: `getBookingNode.resultData` has a user-visible option path; selected `id` flows to the `bookingByTime` `nodeid` field.
- Missing: a user-visible physical venue/campus name tied to that query scope; a same-flow `bookingByTime` request/response association for the selected physical venue; court ownership for the returned `nodeList`.
- Still unverified: availability meaning, price unit/currency/scope, time atom and duration continuity, capture freshness, and a release-level client version.
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
