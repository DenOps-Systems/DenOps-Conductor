# SPDX-License-Identifier: AGPL-3.0-only
import tempfile
import unittest
from pathlib import Path
from app.services.migrations import AppliedMigration, MigrationBlocked, plan_migrations, read_migrations, PostgresMigrationRunner

class Cursor:
    def __init__(self, connection):
        self.connection = connection
    def execute(self, sql, params=None):
        self.connection.events.append((sql, params))
    def fetchone(self):
        return (True,)
    def fetchall(self):
        return []
    def close(self):
        pass

class Connection:
    autocommit = False
    def __init__(self):
        self.events = []
    def cursor(self):
        return Cursor(self)
    def commit(self):
        self.events.append(('commit', None))
    def rollback(self):
        self.events.append(('rollback', None))

class Backup:
    def __init__(self, healthy):
        self.healthy = healthy
    def verify(self, project_id):
        return self.healthy

class MigrationTests(unittest.TestCase):
    def test_checksum_and_numeric_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'0010_later.sql').write_text('CREATE TABLE later (id INT);')
            (root/'0001_first.sql').write_text('CREATE TABLE first (id INT);')
            files = read_migrations(root)
            self.assertEqual([m.number for m in files], [1,10])
            applied = [AppliedMigration(1, files[0].filename, files[0].checksum)]
            self.assertEqual([m.number for m in plan_migrations(files, applied)], [10])
            (root/'0001_first.sql').write_text('CREATE TABLE changed (id INT);')
            with self.assertRaises(MigrationBlocked):
                plan_migrations(read_migrations(root), applied)

    def test_backup_and_review_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'0001_table.sql').write_text('CREATE TABLE example (id INT);')
            files = read_migrations(root)
            runner = PostgresMigrationRunner()
            approved = {files[0].checksum}
            connection = Connection()
            with self.assertRaises(MigrationBlocked):
                runner.run(connection, files, 'a'*40, 1, Backup(False), approved)
            self.assertFalse(any(sql == files[0].sql for sql, _ in connection.events))
            self.assertTrue(any('pg_advisory_unlock' in sql for sql,_ in connection.events))
            connection = Connection()
            runner.run(connection, files, 'a'*40, 1, Backup(True), approved)
            self.assertTrue(any('INSERT INTO denops_schema_migrations' in sql for sql,_ in connection.events))
            (root/'0002_drop.sql').write_text('DROP TABLE example;')
            files = read_migrations(root)
            with self.assertRaises(MigrationBlocked):
                runner.run(Connection(), files, 'a'*40, 1, Backup(True), {m.checksum for m in files})
