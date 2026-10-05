# SPDX-License-Identifier: AGPL-3.0-only
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

class Base(DeclarativeBase):
    pass

def protect_sqlite_file(database_url):
    url = make_url(database_url)
    if url.get_backend_name() != 'sqlite' or not url.database or url.database == ':memory:':
        return
    # Filesystem URLs only; URI query modes need a separate reviewed adapter.
    if url.query.get('uri'):
        raise ValueError('SQLite URI modes are not supported')
    path = Path(url.database)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)

protect_sqlite_file(settings.database_url)
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
Session = sessionmaker(engine, expire_on_commit=False)

def get_db():
    with Session() as session:
        yield session
