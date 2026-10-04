# SPDX-License-Identifier: AGPL-3.0-only
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.services.proxmox import Proxmox
from app.core.config import settings

class ProxmoxTests(unittest.TestCase):
    def test_owner_only_credential_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'secret.env'
            path.write_text('token_id=test@pve!conductor\nsecret=test-only-secret\n')
            path.chmod(0o600)
            with patch.object(settings, 'proxmox_url', 'https://proxmox.example:8006'), patch.object(settings, 'proxmox_token', None), patch.object(settings, 'proxmox_token_file', str(path)), patch('app.services.proxmox.httpx.Client') as client:
                service = Proxmox()
                self.assertEqual(client.call_args.kwargs['headers']['Authorization'], 'PVEAPIToken=test@pve!conductor=test-only-secret')
                self.assertNotEqual(client.call_args.kwargs['verify'], False)
                service.close()
                path.chmod(0o644)
                with self.assertRaises(RuntimeError):
                    Proxmox()
