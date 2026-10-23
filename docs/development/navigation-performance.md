# Navigation and read budgets

## Frontend

- Route views load as separate chunks. The application announces pending navigation while existing authorization and credential guards finish.
- Credential reads share an in-flight request. Mounting controls may reuse a five-second, memory-only DTO snapshot from the same account, Session and invalidation epoch. Route guards and explicit refreshes request fresh data. Credential mutations invalidate snapshots before and after completion.
- Shared calendar/catalog metadata loads once per mounted Session. Token changes reload owned plans and invalidate pending edits without repeating that metadata request.
- Venue categories prepare the manual/Agent scope. Public options also provide the legal 1–10 semantic court labels, so manual selection works before querying inventory. The complete venue grid loads only in the query tab. Execution settings load on expansion; results and administrator metrics load on their first visit.
- Manual drafts and Agent conversations survive tab changes. Account/Session changes still clear private state.
- HTTP deadlines include both response headers and response bodies: 15 seconds for ordinary GETs and read-only venue POSTs; 30 seconds for ordinary mutations; 80 seconds for model planning and parsing tests. Cancellation does not authorize retries of mutations.
- Venue dates coalesce to the latest requested date. An already dispatched read finishes or reaches its deadline before the next date starts, preserving the shared upstream gate. Request-start spacing and server Retry-After remain enforced. Account changes and unmounts abort obsolete browser reads.
- Agent readiness lasts at most five minutes and is keyed by account, model version and Session. Model edits, rotation and provider failures invalidate it. The backend resolves and validates the actual model for each operation.

## Backend

- Two shared model-call slots reserve capacity in the deployed four-thread Web process for ordinary API reads. Slots use nonblocking file locks scoped to the database, including across Web processes. A full service returns `503 ai_service_busy` with Retry-After; the per-user lock and rate limits still apply.
- A 65-second request budget covers all model interpretation, repair and review calls. Connection probes have a ten-second budget; model discovery has twenty seconds. Context propagates through the existing LangGraph runtime; the transport applies the remaining deadline to DNS, connection and reads.
- Conversation history refreshes use a summary endpoint. Listing history reads the last response instead of decoding every stored turn. Full conversation restore retains its existing data and CAS checks.
- Credential lists build their DTOs with one SELECT, including latest validation and payment-password metadata.
- New frontend plan lists request `view=current`: SQL excludes dates before yesterday using the server business timezone. Existing unfiltered service/API calls and immutable history remain available. Metrics filter and count current queues in SQL.
- Version history uses 20-item pages and an exclusive revision cursor. Clients without pagination parameters keep the original full-history response. Account and credential ownership are checked before reading any page.

## Verification and rollout

Run backend unittest discovery in Conda `test`, frontend Vitest/build, synthetic browser E2E, and the Fake Provider/real SQLite planning E2E. Performance browser cases cover eight-or-fewer initial business reads, deferred panels, retained Agent drafts, coalesced dates and stale-response rejection at desktop and phone sizes. These fixtures do not measure real provider speed.

The release requires no database migration or dependency upgrade. Build and review the merged source, back up both databases, retain previous hashed assets, switch the release and restart Web/Worker. Verify the public assets, health, service state and request budgets; roll back the release symlink if those checks fail. Booking executor concurrency, stage delays and payment authorization retain their existing rules.
