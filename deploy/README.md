# Production deployment

The production host uses Cloudflare Tunnel, one loopback-only Nginx virtual
host, one Gunicorn process, one booking scheduler process, and one SQLite
database. Build `frontend/dist` before uploading a release; Node.js is not
required on the server.

## Server paths

- `/opt/yumao-agent/releases/<git-sha>`: immutable application release
- `/opt/yumao-agent/current`: symlink to the active release
- `/opt/yumao-agent/venv`: shared Python virtual environment
- `/var/lib/yumao-agent/yumao.sqlite3`: application database
- `/etc/yumao-agent/yumao.env`: root-owned production configuration
- `/etc/cloudflared/config.yml`: root-owned Tunnel routing configuration

Run migrations before switching `current`. Create the first administrator with
`python -m backend.cli create-admin --username <name>`; enter the password only
at its interactive prompt.

`BOOKING_EXECUTION_ENABLED=true` enables official availability in production
and permits the dedicated worker to run. Never start more than one worker for
the same database.

The public hostname is a proxied CNAME to `<tunnel-id>.cfargotunnel.com`.
Nginx listens only on `127.0.0.1:8080`; the host firewall therefore needs no
public HTTP or HTTPS rule. Keep `TRUST_PROXY_HEADERS=true` only with this
loopback-only Nginx setup; Nginx replaces forwarded client IP and scheme headers
before requests reach Gunicorn.

## Booking email notifications

The optional email feature uses a Cloudflare Email Service Worker because the VM's account REST sender is disabled. Configure the restricted `send_email` binding and Worker HMAC secret as described in `deploy/cloudflare/README.md`; place the same secret only in the root-owned `/etc/yumao-agent/yumao.env`. The application migrates a durable notification outbox and the existing single Worker process dispatches it without making email delivery part of booking/payment success. Configure one app owner username and one verified recipient; other accounts cannot read or change this mailbox setting.
