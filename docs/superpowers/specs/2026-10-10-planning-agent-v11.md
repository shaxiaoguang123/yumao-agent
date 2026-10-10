# Planning Agent V1.1

## Conversation and confirmation

`POST /api/planning/proposals` preserves the single-turn contract
`{message,plan_id,base_version}` and optionally accepts `answers` (ordered user strings)
and `follow_up_questions` (one array of earlier questions per answer).
Questions are untrusted client context for understanding short replies, never field evidence.
Only user text supplies venue/court names or other changed-field evidence.

Limits: original plus at most seven answers; 4000 total user characters / 12000 UTF-8
bytes; 16 KiB request body. Each question group has 1–5 strings, each at most 240
characters. User conversation data stays inside the user JSON message, separate from
server system rules. JSON parsing, semantic validation and source checks remain mandatory.

The page keeps descriptions, earlier questions and accepted answers in memory only.
The first edit read binds the conversation to its owned plan and base version.
Subsequent rounds use that version. A 409 preserves the description and pending answer,
blocks continuation and requires an explicit latest read before regeneration. The
pending answer is included after that read. Account/logout/target changes fence late
responses and clear inapplicable conversation state. Restart clears the conversation.

No generation or clarification writes a PlanRevision. Only the existing explicit
confirmation action calls plan POST/PATCH and PlanService; its optimistic lock remains
the final write guard. Manual planning continues without a configured model.

## Independent capability test

`POST /api/ai/models/<id>/test-parsing` accepts `{}`, requires Session and CSRF, and
uses that exact owned configuration (or complete service default). It never changes
model preferences or borrows another key. It asks the real configured transport to
parse a server synthetic statement using the same PlanningService JSON parser,
`parse_manual_intent` and evidence checks, with no plan context or write operation.

Ready returns `outcome=parsed` plus a read-only preview; clarification returns
`outcome=needs_input`; invalid JSON/schema/evidence returns `invalid_model_proposal`.
Provider errors retain their safe categories. The settings page offers separate
connection and parsing tests, only on explicit clicks. UI error mappings use actual
provider codes and never display raw supplier exceptions, prompts or authorization.
Successful parsing validates this request, not every future model reply.

## Call protection and runtime

Generation, connection tests and parsing tests share SQLite RateLimitService buckets:
12 attempts per user/minute and 120/hour. Rate denials return 429 and Retry-After.
POSIX advisory file locks permit one in-flight model operation per user across local
Flask workers sharing the same database path; closing/crashing releases the lock.
Private `.ai-call-locks/` files beside the database contain no prompts or secrets and
are ignored by Git. This is a single-host safeguard, not a distributed queue.

Schema remains 6. Migrations 0001–0006 are unchanged. Production Provider still accepts
only vetted HTTPS public targets with DNS pinning, TLS validation, deadlines, response
bounds, no redirects and no automatic retries. A separately authorized localhost model
smoke test does not enable localhost/private destinations in application settings.

All intentions remain `unbound_draft / unverified_manual`. No trusted VenueCatalog,
upstream IDs, availability, booking/payment tools or Job/Worker are introduced.
Task 0 remains PARTIAL; Task 1B remains BLOCKED.

## Verification

Synthetic/Fake Provider tests use fresh SQLite and deny external requests. Backend:
303 unittest tests; frontend: 162 Vitest tests and production build. Existing Mock E2E:
77 scenarios / 715 checks; manual plan real integration: 14 checks; updated Planning
Agent real Flask/SQLite runner: 21 checks. Codex browser additionally exercised two
clarifications, confirmation, follow-up editing, history, model failure, a concurrent
update during clarification, explicit latest regeneration and revision 4. Desktop
1440 and phone 390 inspected; phone scroll width equals viewport width.
