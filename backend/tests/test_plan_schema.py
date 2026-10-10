"""Schema guards that protect saved history even outside the service."""
import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.db import CURRENT_SCHEMA_VERSION, SchemaNotReadyError, check_schema_ready, connect_database
from backend.migrate import migrate_database

MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations'


class PlanSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='plan-schema-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'new.sqlite3'
        migrate_database(self.path, 5000)
        self.db = connect_database(self.path, 5000)
        self.addCleanup(self.db.close)
        for name in ('a', 'b'):
            self.db.execute("INSERT INTO users (user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES (?,?,?,'synthetic','user','active',1,1)", (name, name, name))

    def insert_plan(self, plan='p', user='a', revision='r', version=1):
        self.db.execute('INSERT INTO booking_plans VALUES (?,?,?,?,?,?)', (plan, user, revision, version, 1, 1))
        self.db.execute('INSERT INTO booking_plan_revisions VALUES (?,?,?,?,?,?,?,?)', (revision, plan, user, version, '{}', hashlib.sha256(b'{}').hexdigest(), user, 1))

    def test_fresh_chain_and_readiness(self):
        self.assertEqual(CURRENT_SCHEMA_VERSION, 5)
        self.assertEqual([r[0] for r in self.db.execute('SELECT version FROM schema_migrations ORDER BY version')], [1,2,3,4,5])
        check_schema_ready(self.path, 5000, 5)

    def test_pointer_and_revision_are_committed_together(self):
        self.db.execute('BEGIN IMMEDIATE')
        self.insert_plan()
        self.db.execute('COMMIT')
        self.assertIsNone(self.db.execute('PRAGMA foreign_key_check').fetchone())
        for sql in ("UPDATE booking_plan_revisions SET intent_json='[]' WHERE user_id='a'", "DELETE FROM booking_plan_revisions WHERE user_id='a'"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)
        self.assertEqual(self.db.execute('SELECT intent_json FROM booking_plan_revisions').fetchone()[0], '{}')

    def test_failed_pointer_commit_rolls_back_both_rows(self):
        self.db.execute('BEGIN IMMEDIATE')
        self.insert_plan()
        self.db.execute("UPDATE booking_plans SET current_revision_id='absent',version=2 WHERE plan_id='p' AND user_id='a'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('COMMIT')
        self.db.execute('ROLLBACK')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM booking_plans').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM booking_plan_revisions').fetchone()[0], 0)

    def test_cross_plan_cross_user_and_version_pointer_mismatch_fail(self):
        for pointer, version in [('other-r', 2), ('r', 2)]:
            with self.subTest(pointer=pointer):
                self.db.execute('BEGIN IMMEDIATE')
                self.insert_plan()
                self.insert_plan('other', 'b', 'other-r')
                self.db.execute('UPDATE booking_plans SET current_revision_id=?,version=? WHERE plan_id=? AND user_id=?', (pointer,version,'p','a'))
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute('COMMIT')
                self.db.execute('ROLLBACK')

    def test_invalid_versions_and_missing_pointer_rejected(self):
        for revision, version in [(None,1),('r',0),('r',-1)]:
            with self.subTest(version=version):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute('INSERT INTO booking_plans VALUES (?,?,?,?,?,?)', ('p','a',revision,version,1,1))

    def test_readiness_requires_revision_guard(self):
        self.db.execute('DROP TRIGGER booking_plan_revisions_no_update')
        with self.assertRaises(SchemaNotReadyError):
            check_schema_ready(self.path, 5000, 5)

    def test_all_verified_prefixes_preserve_users_and_original_checksums(self):
        for version in (1,2,3,4):
            with self.subTest(version=version):
                prefix = Path(self.tmp.name) / f'prefix-{version}'
                prefix.mkdir()
                for file in sorted(MIGRATIONS.glob('*.sql'))[:version]:
                    shutil.copyfile(file, prefix/file.name)
                path = Path(self.tmp.name) / f'upgrade-{version}.sqlite3'
                migrate_database(path,5000,prefix)
                db = connect_database(path,5000)
                db.execute("INSERT INTO users (user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES ('existing','existing','existing','synthetic','user','active',1,1)")
                before = [tuple(r) for r in db.execute('SELECT version,checksum FROM schema_migrations')]
                db.close()
                migrate_database(path,5000)
                check_schema_ready(path,5000,5)
                db = connect_database(path,5000)
                self.assertEqual(db.execute("SELECT user_id FROM users").fetchone()[0], 'existing')
                self.assertEqual([tuple(r) for r in db.execute('SELECT version,checksum FROM schema_migrations WHERE version<=?',(version,))],before)
                db.close()
