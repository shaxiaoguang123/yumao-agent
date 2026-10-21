# Production deployment

The production host uses one Nginx virtual host, one Gunicorn process, one
booking scheduler process, and one SQLite database. Build `frontend/dist`
before uploading a release; Node.js is not required on the server.

## Server paths

- `/opt/yumao-agent/releases/<git-sha>`: immutable application release
- `/opt/yumao-agent/current`: symlink to the active release
- `/opt/yumao-agent/venv`: shared Python virtual environment
- `/var/lib/yumao-agent/yumao.sqlite3`: application database
- `/etc/yumao-agent/yumao.env`: root-owned production configuration

Run migrations before switching `current`. Create the first administrator with
`python -m backend.cli create-admin --username <name>`; enter the password only
at its interactive prompt.

`BOOKING_EXECUTION_ENABLED=true` enables official availability in production
and permits the dedicated worker to run. Never start more than one worker for
the same database.
