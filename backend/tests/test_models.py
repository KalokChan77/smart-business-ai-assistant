from app.db.base import Base
from app.db.models import Role, User, user_roles


def test_user_role_models_are_registered_in_metadata() -> None:
    assert User.__tablename__ == "users"
    assert Role.__tablename__ == "roles"
    assert user_roles.name == "user_roles"
    assert set(Base.metadata.tables) >= {"users", "roles", "user_roles"}
    assert set(user_roles.c.keys()) == {"user_id", "role_id"}
    assert User.__table__.c.status.type.enums == ["active", "disabled"]
