"""Alembic model registry.

Import every model module here so migration autogeneration sees complete metadata.
"""

from app.ai.models import AIRun
from app.conversations.models import Conversation, Message
from app.customer_service.models import CustomerTicket, ReplySuggestion
from app.feedback.models import AIFeedback
from app.knowledge.documents.models import KnowledgeDocument, KnowledgeSyncJob
from app.users.models import Role, User, user_roles

__all__ = [
    "AIRun",
    "AIFeedback",
    "Conversation",
    "CustomerTicket",
    "KnowledgeDocument",
    "KnowledgeSyncJob",
    "Message",
    "ReplySuggestion",
    "Role",
    "User",
    "user_roles",
]
