# SPDX-License-Identifier: AGPL-3.0-only
from io import BytesIO
from pathlib import Path
import tarfile
import tempfile
import unittest
from app.services.source import source_archive

class SourceTests(unittest.TestCase):
    def test_archive_excludes_secrets_and_runtime_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('app','data','config','logs','migrations','tests'):
                (root/name).mkdir()
            (root/'LICENSE').write_text('AGPL')
            (root/'app'/'main.py').write_text('source')
            (root/'.env').write_text('secret')
            (root/'config'/'secret.env').write_text('secret')
            (root/'data'/'conductor.db').write_text('private')
            (root/'logs'/'production.log').write_text('private')
            (root/'app'/'.private').mkdir()
            (root/'app'/'.private'/'secret.py').write_text('private')
            with tarfile.open(fileobj=BytesIO(source_archive(root)),mode='r:gz') as archive:
                names=set(archive.getnames())
            self.assertEqual(names,{'denops-conductor/LICENSE','denops-conductor/app/main.py'})
            (root/'app'/'escape.py').symlink_to(root/'config'/'secret.env')
            with self.assertRaises(ValueError):
                source_archive(root)
