"""Idempotently create the local teaching demo tenant and four role accounts.

Secrets are never printed. Password is read from DEMO_PASSWORD or a prompt.
Tenant ID comes from DEMO_TENANT_ID or the stable local demo default.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from getpass import getpass
from pathlib import Path
from uuid import UUID

# Ensure backend package imports work when run as a file.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.auth.security import PasswordService
from app.core.asyncio_compat import run_async
from app.core.config import Settings
from app.db.session import Database
from app.users.demo_bootstrap import DEFAULT_DEMO_TENANT_ID, DemoTenantBootstrapper
from app.users.repository import UsersRepository


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize or refresh the local four-role demo tenant.",
    )
    parser.add_argument(
        "--tenant-id",
        default=os.environ.get("DEMO_TENANT_ID"),
        help="Demo tenant UUID. Defaults to DEMO_TENANT_ID or the stable local ID.",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("DEMO_PASSWORD"),
        help="Shared demo password. Defaults to DEMO_PASSWORD or an interactive prompt.",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Overwrite passwords for existing demo accounts.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    settings = Settings()
    if settings.database_url is None:
        raise SystemExit("DATABASE_URL must be configured in .env")

    tenant_id = UUID(args.tenant_id) if args.tenant_id else DEFAULT_DEMO_TENANT_ID
    password = args.password
    if not password:
        password = getpass("演示账号共享密码（至少 8 位，不会回显）: ")
        confirm = getpass("再次输入演示账号密码: ")
        if password != confirm:
            raise SystemExit("两次输入的密码不一致。")

    database = Database.create(settings.database_url.get_secret_value())
    try:
        async with database.session_factory() as session:
            bootstrapper = DemoTenantBootstrapper(
                UsersRepository(session),
                PasswordService(),
            )
            users = await bootstrapper.ensure(
                tenant_id=tenant_id,
                password=password,
                reset_password=args.reset_password,
            )
    finally:
        await database.close()

    print("演示租户已就绪（幂等）。")
    print(f"tenant_id={tenant_id}")
    print("accounts=")
    for user in sorted(users, key=lambda item: item.username):
        roles = ",".join(user.roles)
        print(f"  - username={user.username} roles={roles} status={user.status.value}")
    print("password=<hidden; use DEMO_PASSWORD or the value you entered>")
    print("frontend_login=http://127.0.0.1:5173/login")


if __name__ == "__main__":
    run_async(main())
