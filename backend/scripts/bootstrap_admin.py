import asyncio
from getpass import getpass
from uuid import UUID, uuid4

from app.auth.security import PasswordService
from app.core.config import Settings
from app.db.session import Database
from app.users.repository import UsersRepository
from app.users.schemas import UserCreateRequest
from app.users.service import UserService


async def bootstrap() -> None:
    settings = Settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL must be configured.")

    tenant_text = input("租户 UUID（留空自动生成）: ").strip()
    tenant_id = UUID(tenant_text) if tenant_text else uuid4()
    username = input("管理员用户名: ").strip()
    email = input("管理员邮箱: ").strip()
    password = getpass("管理员密码（至少 8 位）: ")
    confirmation = getpass("再次输入管理员密码: ")
    if password != confirmation:
        raise ValueError("两次输入的密码不一致。")

    validated = UserCreateRequest(
        username=username,
        email=email,
        password=password,
        role_codes={"admin"},
    )

    database = Database.create(settings.database_url.get_secret_value())
    try:
        async with database.session_factory() as session:
            service = UserService(UsersRepository(session), PasswordService())
            admin = await service.bootstrap_admin(
                tenant_id=tenant_id,
                username=validated.username,
                email=validated.email,
                password=validated.password.get_secret_value(),
            )
    finally:
        await database.close()

    print("管理员初始化成功。")
    print(f"tenant_id={admin.tenant_id}")
    print(f"username={admin.username}")


if __name__ == "__main__":
    asyncio.run(bootstrap())
