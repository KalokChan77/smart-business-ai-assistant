from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.auth.principal import Principal
from app.customer_service.models import (
    CustomerServiceKnowledgeOutcome,
    CustomerTicketCategory,
    CustomerTicketPriority,
    ReplyQualityStatus,
)
from app.customer_service.ports import (
    CustomerServiceCitation,
    CustomerServiceKnowledgePort,
    CustomerServiceKnowledgeResult,
    CustomerServiceWorkflowResult,
    TicketClassification,
    TicketClassifier,
)

_WORKFLOW_VERSION = "customer-service-v1"
_MAX_REPLY_LENGTH = 5000
_SENSITIVE_MARKERS = ("api key", "apikey", "cookie", ".env", "private key", "sk-")


class CustomerServiceWorkflowState(TypedDict, total=False):
    principal: Principal
    subject: str
    description: str
    category: CustomerTicketCategory
    priority: CustomerTicketPriority
    confidence: int
    classification_reason: str
    knowledge_outcome: CustomerServiceKnowledgeOutcome
    knowledge_answer: str
    citations: tuple[CustomerServiceCitation, ...]
    suggested_reply: str
    quality_status: ReplyQualityStatus
    quality_notes: tuple[str, ...]


class CustomerServiceWorkflow:
    def __init__(
        self,
        *,
        classifier: TicketClassifier,
        knowledge: CustomerServiceKnowledgePort,
    ) -> None:
        self._classifier = classifier
        self._knowledge = knowledge
        self._graph = self._build_graph()

    async def run(
        self,
        principal: Principal,
        *,
        subject: str,
        description: str,
    ) -> CustomerServiceWorkflowResult:
        result = await self._graph.ainvoke(
            {
                "principal": principal,
                "subject": subject,
                "description": description,
            }
        )
        classification = TicketClassification(
            category=result["category"],
            priority=result["priority"],
            confidence=result["confidence"],
            reason=result["classification_reason"],
        )
        knowledge = CustomerServiceKnowledgeResult(
            outcome=result["knowledge_outcome"],
            answer=result["knowledge_answer"],
            citations=result["citations"],
        )
        return CustomerServiceWorkflowResult(
            classification=classification,
            suggested_reply=result["suggested_reply"],
            knowledge=knowledge,
            quality_status=result["quality_status"],
            quality_notes=result["quality_notes"],
            workflow_version=_WORKFLOW_VERSION,
        )

    def _build_graph(self):
        async def classify(
            state: CustomerServiceWorkflowState,
        ) -> CustomerServiceWorkflowState:
            result = self._classifier.classify(
                state["subject"],
                state["description"],
            )
            return {
                "category": result.category,
                "priority": result.priority,
                "confidence": result.confidence,
                "classification_reason": result.reason,
            }

        async def retrieve_knowledge(
            state: CustomerServiceWorkflowState,
        ) -> CustomerServiceWorkflowState:
            result = await self._knowledge.answer(
                state["principal"],
                state["description"],
            )
            return {
                "knowledge_outcome": result.outcome,
                "knowledge_answer": result.answer,
                "citations": result.citations,
            }

        async def compose_reply(
            state: CustomerServiceWorkflowState,
        ) -> CustomerServiceWorkflowState:
            return {
                "suggested_reply": self._compose_reply(
                    subject=state["subject"],
                    outcome=state["knowledge_outcome"],
                    answer=state["knowledge_answer"],
                )
            }

        async def quality_check(
            state: CustomerServiceWorkflowState,
        ) -> CustomerServiceWorkflowState:
            status, notes = self._quality_check(
                reply=state["suggested_reply"],
                outcome=state["knowledge_outcome"],
                citations=state["citations"],
            )
            return {"quality_status": status, "quality_notes": notes}

        builder = StateGraph(CustomerServiceWorkflowState)
        builder.add_node("classify", classify)
        builder.add_node("retrieve_knowledge", retrieve_knowledge)
        builder.add_node("compose_reply", compose_reply)
        builder.add_node("quality_check", quality_check)
        builder.add_edge(START, "classify")
        builder.add_edge("classify", "retrieve_knowledge")
        builder.add_edge("retrieve_knowledge", "compose_reply")
        builder.add_edge("compose_reply", "quality_check")
        builder.add_edge("quality_check", END)
        return builder.compile(name="customer_service_assistance")

    @staticmethod
    def _compose_reply(
        *,
        subject: str,
        outcome: CustomerServiceKnowledgeOutcome,
        answer: str,
    ) -> str:
        prefix = f"您好，已收到您关于“{subject}”的咨询。"
        if outcome == CustomerServiceKnowledgeOutcome.ANSWERED:
            body = answer.strip()
            suffix = "以上内容来自当前知识库，发送前请结合客户实际情况核对。"
        elif outcome == CustomerServiceKnowledgeOutcome.REFUSED:
            body = "该问题可能涉及敏感配置或隐私信息，不能在回复中提供内部内容。"
            suffix = "请按安全流程核验身份，并由客服进一步处理。"
        else:
            body = "当前知识库没有找到足够依据，暂时不能给出确定结论。"
            suffix = "请客服核实业务记录或咨询负责人后再向客户回复。"
        return f"{prefix}\n{body}\n{suffix}"[:_MAX_REPLY_LENGTH]

    @staticmethod
    def _quality_check(
        *,
        reply: str,
        outcome: CustomerServiceKnowledgeOutcome,
        citations: tuple[CustomerServiceCitation, ...],
    ) -> tuple[ReplyQualityStatus, tuple[str, ...]]:
        notes: list[str] = []
        normalized = reply.casefold()
        if outcome != CustomerServiceKnowledgeOutcome.ANSWERED:
            notes.append("知识依据不足或触发安全拒答，必须人工核实。")
        if outcome == CustomerServiceKnowledgeOutcome.ANSWERED and not citations:
            notes.append("知识回答缺少引用，必须人工核实。")
        if any(marker in normalized for marker in _SENSITIVE_MARKERS):
            notes.append("建议中出现敏感配置相关标记，禁止直接发送。")
        if not reply.strip():
            notes.append("建议回复为空。")

        if notes:
            return ReplyQualityStatus.NEEDS_REVIEW, tuple(notes)
        return ReplyQualityStatus.PASSED, ()
