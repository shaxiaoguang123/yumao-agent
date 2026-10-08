from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import credential_test_settings


# Importing the recovered legacy app at the red phase must not inspect the
# developer's project root. Give any legacy import a clean synthetic root.
_TEST_ROOT = tempfile.TemporaryDirectory(prefix="yumao-app-factory-")
os.environ["APP_ROOT_DIR"] = _TEST_ROOT.name
os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def _module(name: str):
    if importlib.util.find_spec(name) is None:
        raise AssertionError(f"{name} must provide the V1 API")
    return importlib.import_module(name)


def _migrate_database(database_path: Path) -> None:
    if importlib.util.find_spec("backend.migrate") is None:
        raise AssertionError("backend.migrate must be available to prepare the test database")
    importlib.import_module("backend.migrate").migrate_database(database_path, 5000)


def _create_app(database_path: Path):
    module = importlib.import_module("backend.app")
    factory = getattr(module, "create_app", None)
    if not callable(factory):
        raise AssertionError("backend.app must expose create_app")
    return factory({"TESTING": True, **credential_test_settings(database_path)})


class AppFactoryTests(unittest.TestCase):
    def test_create_app_uses_injected_database_path(self) -> None:
        database_path = Path(_TEST_ROOT.name) / "identity-test.sqlite3"
        _migrate_database(database_path)
        app = _create_app(database_path)
        self.assertEqual(app.config["DATABASE_PATH"], database_path)

    def test_health_endpoint_is_public_and_minimal(self) -> None:
        database_path = Path(_TEST_ROOT.name) / "health.sqlite3"
        _migrate_database(database_path)
        response = _create_app(database_path).test_client().get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_v1_app_does_not_register_legacy_mutation_routes(self) -> None:
        database_path = Path(_TEST_ROOT.name) / "routes.sqlite3"
        _migrate_database(database_path)
        app = _create_app(database_path)
        routes = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertNotIn("/api/run", routes)
        self.assertNotIn("/api/save_plan", routes)

    def test_app_factory_does_not_copy_raw_credential_keyrings_into_flask_config(self) -> None:
        database_path = Path(_TEST_ROOT.name) / "credential-config.sqlite3"
        _migrate_database(database_path)
        app = _create_app(database_path)

        for name in (
            "APP_CREDENTIAL_ENCRYPTION_KEYS",
            "APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID",
            "APP_UPSTREAM_FINGERPRINT_KEYS",
            "APP_UPSTREAM_FINGERPRINT_ACTIVE_KEY_ID",
        ):
            self.assertNotIn(name, app.config, f"raw setting {name} entered Flask config")
        self.assertNotIn(
            "enc-v1", repr(app.config), "encryption key ID entered Flask config"
        )
        self.assertNotIn(
            "fp-v1", repr(app.config), "fingerprint key ID entered Flask config"
        )

    def test_app_factory_rejects_unready_database_without_creating_it(self) -> None:
        db = _module("backend.db")
        database_path = Path(_TEST_ROOT.name) / "must-not-be-created.sqlite3"
        with self.assertRaises(db.SchemaNotReadyError):
            _create_app(database_path)
        self.assertFalse(database_path.exists())

    def test_app_factory_rejects_database_without_schema_migrations(self) -> None:
        db = _module("backend.db")
        database_path = Path(_TEST_ROOT.name) / "no-migrations.sqlite3"
        db = _module("backend.db")
        conn = db.connect_database(database_path, 5000)
        conn.close()
        with self.assertRaises(db.SchemaNotReadyError):
            _create_app(database_path)

    def test_app_factory_requires_schema_v3_without_running_migrations(self) -> None:
        db = _module("backend.db")
        migrate_database = _module("backend.migrate").migrate_database
        root = Path(_TEST_ROOT.name)
        database_path = root / "legacy-schema.sqlite3"
        schema_v2_migrations = root / "schema-v2-migrations"
        schema_v2_migrations.mkdir()
        migration_dir = Path(__file__).resolve().parents[1] / "migrations"
        for name in ("0001_identity.sql", "0002_credentials.sql"):
            shutil.copyfile(migration_dir / name, schema_v2_migrations / name)
        migrate_database(database_path, 5000, schema_v2_migrations)

        self.assertEqual(db.CURRENT_SCHEMA_VERSION, 3)
        with self.assertRaises(db.SchemaNotReadyError):
            _create_app(database_path)

        conn = db.connect_database(database_path, 5000)
        try:
            versions = [
                row[0] for row in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            self.assertEqual(versions, [1, 2])
        finally:
            conn.close()


def tearDownModule() -> None:
    logging.shutdown()
    _TEST_ROOT.cleanup()
