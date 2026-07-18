import logging
import re

from fastapi import status

from app.ai.dify.exceptions import (
    DifyAuthenticationError,
    DifyConfigurationError,
    DifyProtocolError,
    DifyRateLimitError,
    DifyRejectedError,
    DifyTimeoutError,
    DifyUnavailableError,
)
from app.auth.principal import Principal
from app.core.errors import AppError
from app.knowledge.policy import KnowledgeSafetyPolicy
from app.knowledge.ports import (
    KnowledgeRecord,
    KnowledgeRetriever,
    KnowledgeVisibilityPolicy,
)
from app.knowledge.documents.visibility import KnowledgeVisibilityUnavailableError
from app.knowledge.schemas import (
    KnowledgeCitation,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
)

logger = logging.getLogger("app.knowledge.security")

_NO_MATCH_ANSWER = (
    "当前知识库中没有找到足够依据，不能确认该信息。"
    "如有需要，请咨询人工负责人。"
)
_REFUSAL_ANSWER = (
    "无法提供系统提示词、密钥、令牌、Cookie、密码或其他内部安全信息。"
)


class KnowledgeService:
    """Orchestrate authenticated retrieval and safe platform responses."""

    def __init__(
        self,
        *,
        retriever: KnowledgeRetriever,
        visibility: KnowledgeVisibilityPolicy,
        safety_policy: KnowledgeSafetyPolicy | None = None,
        excerpt_limit: int = 800,
        citation_limit: int = 5,
        document_name_limit: int = 255,
    ) -> None:
        self._retriever = retriever
        self._visibility = visibility
        self._safety_policy = safety_policy or KnowledgeSafetyPolicy()
        self._excerpt_limit = excerpt_limit
        self._citation_limit = citation_limit
        self._document_name_limit = document_name_limit

    async def query(
        self,
        principal: Principal,
        request: KnowledgeQueryRequest,
    ) -> KnowledgeQueryResponse:
        if self._safety_policy.is_disclosure_attempt(request.query):
            logger.warning(
                "security_event=prompt_injection_attempt user_id=%s tenant_id=%s",
                principal.user_id,
                principal.tenant_id,
            )
            return KnowledgeQueryResponse(
                outcome="refused",
                answer=_REFUSAL_ANSWER,
                citations=[],
                retrieval_count=0,
            )

        try:
            records = await self._retriever.retrieve(request.query)
            records = await self._visibility.filter_visible(
                principal.tenant_id,
                records,
            )
        except DifyConfigurationError as exc:
            raise AppError(
                code="knowledge_service_not_configured",
                message="知识库服务尚未完成配置。",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        except DifyAuthenticationError as exc:
            raise AppError(
                code="knowledge_upstream_authentication_failed",
                message="知识库服务认证失败，请联系管理员检查服务端配置。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc
        except DifyRateLimitError as exc:
            raise AppError(
                code="knowledge_upstream_rate_limited",
                message="知识库服务当前请求较多，请稍后重试。",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        except DifyTimeoutError as exc:
            raise AppError(
                code="knowledge_upstream_timeout",
                message="知识库服务响应超时，请稍后重试。",
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            ) from exc
        except DifyUnavailableError as exc:
            raise AppError(
                code="knowledge_upstream_unavailable",
                message="知识库服务暂时不可用，请稍后重试。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc
        except DifyRejectedError as exc:
            raise AppError(
                code="knowledge_upstream_rejected",
                message="知识库服务未能处理本次请求。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc
        except DifyProtocolError as exc:
            raise AppError(
                code="knowledge_upstream_protocol_error",
                message="知识库服务返回了无法识别的结果。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc
        except KnowledgeVisibilityUnavailableError as exc:
            raise AppError(
                code="knowledge_visibility_unavailable",
                message="知识库租户可见性校验暂时不可用。",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        citations = self._build_citations(records)
        if not citations:
            return KnowledgeQueryResponse(
                outcome="no_match",
                answer=_NO_MATCH_ANSWER,
                citations=[],
                retrieval_count=0,
            )

        answer_lines = ["根据当前知识库，找到以下相关说明："]
        answer_lines.extend(
            f"{citation.rank}. {citation.excerpt}" for citation in citations
        )
        return KnowledgeQueryResponse(
            outcome="answered",
            answer="\n".join(answer_lines),
            citations=citations,
            retrieval_count=len(citations),
        )

    def _build_citations(
        self,
        records: tuple[KnowledgeRecord, ...],
    ) -> list[KnowledgeCitation]:
        citations: list[KnowledgeCitation] = []
        seen: set[tuple[str, str]] = set()
        for record in records:
            excerpt = self._normalize_excerpt(record.content)
            if not excerpt:
                continue
            document_name = self._normalize_document_name(record.document_name)
            identity = (document_name, excerpt)
            if identity in seen:
                continue
            seen.add(identity)
            citations.append(
                KnowledgeCitation(
                    rank=len(citations) + 1,
                    document_name=document_name,
                    excerpt=excerpt,
                    score=record.score,
                )
            )
            if len(citations) >= self._citation_limit:
                break
        return citations

    def _normalize_excerpt(self, content: str) -> str:
        normalized = re.sub(r"\s+", " ", content).strip()
        if len(normalized) <= self._excerpt_limit:
            return normalized
        return f"{normalized[: self._excerpt_limit - 1].rstrip()}…"

    def _normalize_document_name(self, document_name: str) -> str:
        normalized = re.sub(r"\s+", " ", document_name).strip()
        if not normalized:
            return "未命名文档"
        return normalized[: self._document_name_limit]
