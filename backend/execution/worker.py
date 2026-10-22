from __future__ import annotations


def main() -> None:
    from backend.app import create_app
    from backend.diagnostics import diagnostic_scope, record_event

    app = create_app(process_role="worker")
    diagnostics = app.extensions["runtime_diagnostics"]
    with diagnostic_scope(diagnostics):
        try:
            app.extensions["booking_scheduler"].run_forever()
        except Exception as exc:
            record_event("system", "worker.stopped", level="error", code="worker_internal_error", exception=exc)
            raise SystemExit(1) from None
        finally:
            diagnostics.close()


if __name__ == "__main__":
    main()
