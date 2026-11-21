"""Product reference data (FR-ARCH-03): everything product-specific lives in a YAML file, not in code.

The service itself knows nothing about document names, section numbers or expected answers. The file
describes what cannot be derived from the knowledge base: host names of internal links, the documented
filter syntax, document aliases. Without the file the deterministic tools report that they are not set up.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

from .config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def get_product() -> dict:
    path = Path(get_settings().product_file)
    if not path.exists():
        log.warning("product file %s not found: validate_filter / parse_bo_link have no reference data", path)
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def section(name: str) -> dict:
    v = get_product().get(name)
    return v if isinstance(v, dict) else {}
