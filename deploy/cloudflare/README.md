# Booking email notification Worker

The booking app runs on a VM, so it calls this Worker over HTTPS. The Worker sends through Cloudflare's native `send_email` binding; this deployment does not need a REST Email Sending API token.

Use `wrangler.jsonc` as the deploy template for `yumao-booking-email` (replace the example sender and verified destination with the configured values), then set the Worker secret and deploy. Do not put a real destination address or secret into Git. Add these bindings/variables:

- `EMAIL`: `send_email` binding with `destination_address` set to the verified mailbox and `allowed_sender_addresses` limited to the configured sender.
- `EMAIL_FROM`: an address on the onboarded domain.
- `EMAIL_FROM_NAME`: `羽毛球预约通知`.
- `BACKEND_HMAC_SECRET`: a random 32-byte value, set as a Worker secret.

For a manual rollout, deploy the script from this directory with Wrangler, set `BACKEND_HMAC_SECRET` with `wrangler secret put`, and set the Workers.dev subdomain enabled. The API-based rollout uses the same module and binding/variable names.

The same 64-character lowercase hex secret and the Worker HTTPS `/notify` URL belong in root-owned `/etc/yumao-agent/yumao.env` with `EMAIL_NOTIFICATION_OWNER_USERNAME`, `EMAIL_NOTIFICATION_RECIPIENT`, and `EMAIL_NOTIFICATION_DEFAULT_ENABLED`. Never put the secret or real recipient into Git.

Only the configured app owner can enable notifications. The Worker accepts signed, timestamped reminder/result payloads, fixes the recipient through the binding, renders both plain text and escaped HTML, and returns a provider message ID. The backend outbox retries explicit transient provider responses; an ambiguous timeout is marked for review to avoid duplicate mail.
