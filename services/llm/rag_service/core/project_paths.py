"""Project-isolated upload directories; retain the legacy folder for the default project."""

import hashlib
import os
import tempfile
from pathlib import Path


def upload_dir(settings, project_id: str) -> Path:
    root = Path(settings.kb_dir)
    if project_id == settings.default_project_id:
        return root
    key = hashlib.sha256(project_id.encode()).hexdigest()
    return root.parent / (root.name + "_projects") / key


def write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".upload-", delete=False) as output:
            temp = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
