from fastapi import APIRouter

from app.agent.router import router as agent_router
from app.ai.router import router as ai_router
from app.analytics.router import router as analytics_router
from app.audio.router import router as audio_router
from app.auth.router import router as auth_router
from app.conversations.router import router as conversations_router
from app.customer_service.router import router as customer_service_router
from app.feedback.router import router as feedback_router
from app.health.router import router as health_router
from app.knowledge.router import router as knowledge_router
from app.knowledge.documents.router import router as knowledge_documents_router
from app.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(agent_router)
api_router.include_router(ai_router)
api_router.include_router(analytics_router)
api_router.include_router(audio_router)
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(customer_service_router)
api_router.include_router(feedback_router)
api_router.include_router(knowledge_router)
api_router.include_router(knowledge_documents_router)
api_router.include_router(users_router)
