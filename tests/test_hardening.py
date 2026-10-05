# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from starlette.requests import Request
from app.core.database import protect_sqlite_file
from app.core.request_limits import RequestSizeLimit
from app.core.security import authorize
from app.services.source import SourceArchiveCache

class HardeningTests(unittest.TestCase):
    def test_database_permissions_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            database=root/'db.sqlite'
            database.write_text('')
            database.chmod(0o644)
            protect_sqlite_file('sqlite:///'+str(database))
            self.assertEqual(database.stat().st_mode & 0o777,0o600)
            link=root/'alias.sqlite'
            link.symlink_to(database)
            with self.assertRaises(OSError):
                protect_sqlite_file('sqlite:///'+str(link))

    def test_non_ascii_credentials_rejected(self):
        request=Request({'type':'http','headers':[(b'authorization',b'Bearer \xff')]})
        with self.assertRaises(HTTPException) as error:
            authorize(request)
        self.assertEqual(error.exception.status_code,401)

    def test_archive_compressed_only_once_under_concurrency(self):
        cache=SourceArchiveCache()
        with patch('app.services.source.source_archive',return_value=b'source') as build:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(lambda _:cache.get(),range(16)))
            self.assertEqual(results,[b'source']*16)
            build.assert_called_once()

    def test_request_limit_handles_streams_and_declared_lengths(self):
        async def run(headers,messages):
            sent=[]
            passed=[]
            async def receive():
                return messages.pop(0)
            async def send(message):
                sent.append(message)
            async def application(scope,receive,send):
                passed.append((await receive())['body'])
                await send({'type':'http.response.start','status':200,'headers':[]})
                await send({'type':'http.response.body','body':b'ok'})
            await RequestSizeLimit(application,max_bytes=4)({'type':'http','headers':headers},receive,send)
            return sent[0]['status'],passed
        request=lambda body,more=False:{'type':'http.request','body':body,'more_body':more}
        self.assertEqual(asyncio.run(run([], [request(b'ab',True),request(b'cd')])),(200,[b'abcd']))
        self.assertEqual(asyncio.run(run([], [request(b'abc',True),request(b'de')]))[0],413)
        self.assertEqual(asyncio.run(run([(b'content-length',b'5')],[]))[0],413)
        self.assertEqual(asyncio.run(run([(b'content-length',b'bad')],[]))[0],400)
