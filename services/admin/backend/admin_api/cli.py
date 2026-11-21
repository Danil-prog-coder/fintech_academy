"""Operator CLI: integrations are created by the platform operator, never through the public API.

    python -m admin_api.cli integration-create <slug> "<Name>"     → prints the key once
    python -m admin_api.cli integration-rotate <slug>              → new key, the old one stops working
    python -m admin_api.cli integration-revoke <slug>
    python -m admin_api.cli integration-list
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from . import db
from .config import get_settings
from .models import Integration
from .services import integrations


async def _run(argv: list[str]) -> int:
    db.init_engine(get_settings().database_url)
    try:
        async with db.sessionmaker()() as s:
            cmd = argv[0] if argv else ""
            if cmd == "integration-create" and len(argv) == 3:
                integ, key = await integrations.create(s, argv[1], argv[2])
                await s.commit()
                print(f"integration {integ.slug} created\nX-Api-Key: {key}\n(the key is shown once)")
            elif cmd in ("integration-rotate", "integration-revoke") and len(argv) == 2:
                integ = await s.scalar(select(Integration).where(Integration.slug == argv[1]))
                if integ is None:
                    print("no such integration", file=sys.stderr)
                    return 1
                if cmd == "integration-rotate":
                    key = await integrations.rotate_key(s, integ)
                    await s.commit()
                    print(f"X-Api-Key: {key}")
                else:
                    await integrations.revoke(s, integ)
                    print("revoked")
            elif cmd == "integration-list":
                for i in (await s.scalars(select(Integration).order_by(Integration.id))).all():
                    state = "revoked" if i.revoked_at else "active"
                    print(f"{i.slug}\t{i.name}\t{i.key_prefix}…\t{state}\twebhook={i.webhook_url or '-'}")
            else:
                print(__doc__)
                return 2
    finally:
        await db.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(sys.argv[1:])))
