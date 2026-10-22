# Official order queries

The fifth `/plans` tab queries the selected user's Token, including orders created
in the official client. It does not create, pay, cancel, or refund an order.

- `POST /api/orders/query`: `credential_id`, optional `page` (1–10000),
  `page_size` (1–50), and official `status` (1–15, or empty for all).
- `POST /api/orders/details`: `credential_id` and the signed `reference` issued
  by a list query. References expire after ten minutes and bind user, application
  session, credential version, Token revision, and the upstream order identifiers.
- Both endpoints require the application session, CSRF and trusted Origin. The
  existing Credential read gate checks Token ownership, lifecycle and throttling.
  The browser never receives a Token or payment secret; response fields exclude
  upstream identity, phone numbers and QR codes. Responses use `Cache-Control: no-store`.
- Queries need no payment password. Booking tabs retain their existing setup guard.
- Upstream amounts are minor units; the official client displays them divided by
  100. String/Decimal conversion avoids binary floating point. Unknown amounts and
  statuses stay unknown instead of becoming zero or a successful reservation.
- The official `expirationTime` is a usage deadline in the captured response, not
  proof of an unpaid order's payment deadline. The UI explains the upstream's
  five-minute cancellation rule, and refreshes use the returned official status.

`backend/orders/status.py` shares the fifteen official status labels and confirmed
reservation statuses (1, 4, 6, 8) with the executor. An upstream `success: true` means
the query succeeded, not that payment succeeded. Non-empty `paytime` never proves
payment: a real unpaid status-5 order returned a timestamp in the detail response.
Failed query envelopes, pending, cancelled, expired and unknown states cannot mark
an execution as succeeded.

Tests use synthetic upstream data and temporary SQLite databases. Live acceptance
must use read-only endpoints and must not create or pay an order.
