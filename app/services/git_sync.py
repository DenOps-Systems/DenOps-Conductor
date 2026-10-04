# SPDX-License-Identifier: AGPL-3.0-only
"""Local workspace operations. Caller must select a dedicated, trusted workspace."""
from pathlib import Path
import re
import subprocess

class GitSync:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve(strict=True)
        if not (self.workspace / '.git').exists():
            raise ValueError('Workspace must be an existing Git checkout')

    def run(self, *arguments):
        return subprocess.run(['git', '-C', str(self.workspace), *arguments], check=True, capture_output=True, text=True, timeout=120).stdout.strip()

    def synchronize(self, production_commit: str):
        if not re.fullmatch(r'[a-f0-9]{40}', production_commit):
            raise ValueError('Exact production commit required')
        # Refuse to destroy local investigation work.
        if self.run('status', '--porcelain'):
            raise RuntimeError('Workspace has local changes; review before synchronizing')
        self.run('fetch', '--prune', 'origin')
        if self.run('rev-parse', '--verify', production_commit + '^{commit}') != production_commit:
            raise RuntimeError('Production commit is not available')
        self.run('checkout', '--detach', production_commit)
        actual = self.run('rev-parse', 'HEAD')
        if actual != production_commit:
            raise RuntimeError('Builder commit verification failed')
        return actual
