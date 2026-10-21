"""Conservative advisory cache for deterministic, digest-pinned lint checks.

Never use this cache for mandatory policy gates or to authenticate test runs.
Cached results are marked 'cached-passed', not 'passed'. At present ONLY the
Ruff file-level adapter is eligible; build/test runners must execute afresh.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from changeattest.adapters import Adapter
from changeattest.engine import canonical

SCHEMA = 'changeattest.advisory-cache.v1'
_CACHEABLE = frozenset({'ruff'})
_MAX_AGE_SECONDS = 3600
_MAX_CACHE_ENTRY_BYTES = 8192


class AdvisoryCache:
    def __init__(self, cache_dir: Path, root: Path, image: str):
        self.root = root.resolve(strict=True)
        self.path = cache_dir.expanduser().resolve()
        if self.path.is_relative_to(self.root):
            raise ValueError('Cache directory must be outside the target repository')
        if '@sha256:' not in image:
            raise ValueError('Cache requires a digest-pinned sandbox image')
        self.image = image
        self.commit, self.tree = self._clean_git_identity()
        self.path.mkdir(parents=True, exist_ok=True)

    def _git(self, *args: str) -> bytes:
        try:
            run = subprocess.run(('git', *args), cwd=self.root,
                                 capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError('Unable to verify clean Git checkout') from exc
        if run.returncode:
            raise ValueError('Unable to verify clean Git checkout')
        return run.stdout.strip()

    def _clean_git_identity(self) -> tuple[str, str]:
        if self._git('status', '--porcelain', '-z', '--untracked-files=all'):
            raise ValueError('Advisory cache requires a clean Git checkout')
        head = self._git('rev-parse', 'HEAD').decode('ascii')
        tree = self._git('rev-parse', 'HEAD^{tree}').decode('ascii')
        if len(head) not in (40, 64) or len(tree) != len(head):
            raise ValueError('Invalid Git identity')
        return head, tree

    def eligible(self, adapter: Adapter) -> bool:
        return adapter.id in _CACHEABLE

    def _key(self, adapter: Adapter, selected: list[str]) -> str:
        return hashlib.sha256(canonical({
            'schema': SCHEMA,
            'tree': self.tree,
            'commit': self.commit,
            'image': self.image,
            'id': adapter.id,
            'command': list(adapter.command),
            'files': sorted(selected),
        })).hexdigest()

    def get(self, adapter: Adapter, selected: list[str]) -> dict[str, Any] | None:
        if not self.eligible(adapter) or not selected:
            return None
        key = self._key(adapter, selected)
        filename = self.path / f'{key}.json'
        try:
            if filename.stat().st_size > _MAX_CACHE_ENTRY_BYTES:
                return None
            record = json.loads(filename.read_text(encoding='utf-8'))
            if (
                type(record) is not dict or record.get('schema') != SCHEMA or
                record.get('key') != key or
                record.get('status') != 'passed' or
                type(record.get('created_unix')) not in (float, int) or
                not 0 <= time.time() - record['created_unix'] <= _MAX_AGE_SECONDS or
                type(record.get('result')) is not dict
            ):
                return None
            original = record['result']
            if not (
                original.get('id') == adapter.id and
                original.get('status') == 'passed' and
                original.get('exit_code') == 0 and
                original.get('file_count') == len(selected) and
                original.get('sandbox_image') == self.image
            ):
                return None
            return {
                **original, 'status': 'cached-passed', 'cached': True,
                'cache_trust': 'advisory-unsigned', 'cache_key': key,
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def put(self, adapter: Adapter, selected: list[str],
            result: dict[str, Any]) -> None:
        if (
            not self.eligible(adapter) or not selected or
            result.get('status') != 'passed' or
            result.get('exit_code') != 0 or
            result.get('id') != adapter.id or
            result.get('sandbox_image') != self.image or
            result.get('file_count') != len(selected)
        ):
            return
        key = self._key(adapter, selected)
        entry = {
            'schema': SCHEMA, 'key': key,
            'status': 'passed', 'created_unix': time.time(),
            'result': result,
        }
        contents = canonical(entry)
        if len(contents) > _MAX_CACHE_ENTRY_BYTES:
            return
        fd, tmp = tempfile.mkstemp(prefix='.ca-', suffix='.tmp', dir=self.path)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(contents)
            os.replace(tmp, self.path / f'{key}.json')
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
