from typing import Annotated

from fastapi import Depends

from app.auth.dependencies import get_password_service, get_users_repository
from app.auth.security import PasswordService
from app.users.repository import UsersRepository
from app.users.service import UserService


def get_user_service(
    repository: Annotated[UsersRepository, Depends(get_users_repository)],
    passwords: Annotated[PasswordService, Depends(get_password_service)],
) -> UserService:
    return UserService(repository, passwords)
