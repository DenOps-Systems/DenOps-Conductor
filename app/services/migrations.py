# SPDX-License-Identifier: AGPL-3.0-only
"""Release migration planning and PostgreSQL execution; never reverses migrations."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
import re
import time

class MigrationBlocked(RuntimeError):
    pass

@dataclass(frozen=True)
class SQLMigration:
    number: int
    filename: str
    checksum: str
    sql: str
    requires_review: bool

@dataclass(frozen=True)
class AppliedMigration:
    number: int
    filename: str
    checksum: str

class BackupVerifier(Protocol):
    def verify(self, project_id: int) -> bool: ...

# Conservative review classification, not a proof of SQL safety. All production
# schema changes still require explicit approval in the initial runner.
RISK = re.compile(r'\b(DROP|TRUNCATE|DELETE|UPDATE|ALTER\s+TYPE|ALTER\s+COLUMN|EXECUTE|CALL|DO|COPY|CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION)\b', re.I)
TRANSACTION_CONTROL = re.compile(r'\b(BEGIN|COMMIT|ROLLBACK|VACUUM|CONCURRENTLY)\b', re.I)

def read_migrations(directory: Path) -> list[SQLMigration]:
    if directory.is_symlink() or not directory.is_dir():
        raise MigrationBlocked('Migration directory must exist and cannot be a symlink')
    result = []
    for path in sorted(directory.glob('*.sql')):
        match = re.fullmatch(r'(\d{4,})_([a-zA-Z0-9_-]+)\.sql', path.name)
        if not match or path.is_symlink() or not path.is_file():
            raise MigrationBlocked('Invalid migration file: ' + path.name)
        raw = path.read_bytes()
        sql = raw.decode('utf-8')
        result.append(SQLMigration(int(match[1]), path.name, sha256(raw).hexdigest(), sql, bool(RISK.search(sql))))
    result.sort(key=lambda migration: migration.number)
    if len({m.number for m in result}) != len(result) or any(m.number <= 0 for m in result):
        raise MigrationBlocked('Duplicate or invalid migration numbers')
    return result

def plan_migrations(files: list[SQLMigration], applied: list[AppliedMigration]):
    by_number = {m.number: m for m in files}
    if len(by_number) != len(files) or len({m.number for m in applied}) != len(applied):
        raise MigrationBlocked('Duplicate migration numbers')
    for record in applied:
        file = by_number.get(record.number)
        if file is None or file.filename != record.filename or file.checksum != record.checksum:
            raise MigrationBlocked(f'Applied migration {record.number} is missing or changed')
    numbers = {m.number for m in applied}
    pending = sorted((m for m in files if m.number not in numbers), key=lambda m: m.number)
    if applied and any(m.number <= max(numbers) for m in pending):
        raise MigrationBlocked('Cannot insert a migration before the applied ledger')
    return pending

class PostgresMigrationRunner:
    """Accepts a DB-API PostgreSQL connection supplied by the trusted publisher.

    Connection must be idle and autocommit disabled. Every migration and ledger
    entry commits together. A session advisory lock spans all migration commits.
    Nontransactional SQL is deliberately refused pending a reviewed adapter.
    """
    def run(self, connection, files, release_commit, project_id, backup: BackupVerifier, approved_checksums=frozenset(), reviewed_checksums=frozenset()):
        if not re.fullmatch(r'[a-f0-9]{40}', release_commit):
            raise MigrationBlocked('Exact release commit required')
        if connection.autocommit:
            raise MigrationBlocked('Transactional connection required')
        cursor = connection.cursor()
        locked = False
        try:
            cursor.execute('SELECT pg_try_advisory_lock(%s)', (730198641,))
            locked = bool(cursor.fetchone()[0])
            if not locked:
                raise MigrationBlocked('Another migration runner holds the database lock')
            cursor.execute('''CREATE TABLE IF NOT EXISTS denops_schema_migrations (
                migration_number BIGINT PRIMARY KEY, filename TEXT NOT NULL,
                sha256 TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                release_commit TEXT NOT NULL, execution_duration_ms BIGINT NOT NULL)''')
            cursor.execute('SELECT migration_number, filename, sha256 FROM denops_schema_migrations ORDER BY migration_number')
            applied = [AppliedMigration(*row) for row in cursor.fetchall()]
            pending = plan_migrations(files, applied)
            if pending:
                if not all(m.checksum in approved_checksums for m in pending):
                    raise MigrationBlocked('Schema changes require release approval')
                if any(m.requires_review and m.checksum not in reviewed_checksums for m in pending):
                    raise MigrationBlocked('High-risk migration requires explicit review')
                if any(TRANSACTION_CONTROL.search(m.sql) for m in pending):
                    raise MigrationBlocked('Nontransactional or transaction-control SQL requires a separate reviewed runner')
                if backup.verify(project_id) is not True:
                    raise MigrationBlocked('Backup/WAL health could not be verified')
            connection.commit()
            for migration in pending:
                start = time.monotonic()
                cursor.execute(migration.sql)
                cursor.execute('INSERT INTO denops_schema_migrations (migration_number, filename, sha256, release_commit, execution_duration_ms) VALUES (%s, %s, %s, %s, %s)', (migration.number, migration.filename, migration.checksum, release_commit, int((time.monotonic()-start)*1000)))
                connection.commit()
            return pending
        except Exception:
            connection.rollback()
            raise
        finally:
            try:
                if locked:
                    cursor.execute('SELECT pg_advisory_unlock(%s)', (730198641,))
                    connection.commit()
            finally:
                cursor.close()
