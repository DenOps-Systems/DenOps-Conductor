# SPDX-License-Identifier: AGPL-3.0-only
"""Explicit first-party source allowlist; never archive the entire workspace."""
from io import BytesIO
from pathlib import Path
import tarfile
from threading import Lock

ROOT = Path(__file__).resolve().parents[2]
FILES = ('LICENSE', 'README.md', 'CONTRIBUTING.md', 'requirements.txt', 'alembic.ini', '.env.example', '.gitignore')

def source_archive(root: Path = ROOT) -> bytes:
    root = root.resolve()
    candidates = [root / name for name in FILES]
    for directory in ('app', 'migrations', 'tests'):
        base = root / directory
        if base.is_symlink():
            raise ValueError('Source directory cannot be a symlink')
        candidates.extend(base.rglob('*.py'))
        if directory == 'app':
            for suffix in ('*.js', '*.css', '*.html', '*.png'):
                candidates.extend(base.rglob(suffix))
        if directory == 'migrations':
            candidates.extend(base.rglob('*.mako'))
    output = BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for path in sorted(set(candidates)):
            if not path.is_file():
                continue
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
                raise ValueError('Source files cannot use symlinks')
            relative = path.relative_to(root)
            if any(part.startswith('.') or part == '__pycache__' for part in relative.parts) and str(relative) not in FILES:
                continue
            raw = path.read_bytes()
            info = tarfile.TarInfo('denops-conductor/' + relative.as_posix())
            info.size = len(raw)
            info.mode = 0o644
            archive.addfile(info, BytesIO(raw))
    return output.getvalue()


class SourceArchiveCache:
    """One source snapshot per worker lifetime, serialized on first request.

    Deployments must restart workers with their immutable release source.
    """
    def __init__(self, root=ROOT):
        self.root = root
        self._lock = Lock()
        self._archive = None

    def get(self):
        with self._lock:
            if self._archive is None:
                self._archive = source_archive(self.root)
            return self._archive

source_cache = SourceArchiveCache()
