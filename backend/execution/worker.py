from __future__ import annotations


def main() -> None:
    from backend.app import create_app

    app = create_app()
    app.extensions["booking_scheduler"].run_forever()


if __name__ == "__main__":
    main()
