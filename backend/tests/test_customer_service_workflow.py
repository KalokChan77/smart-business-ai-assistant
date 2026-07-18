from uuid import uuid4

from app.auth.principal import Principal
from app.customer_service.classification import RuleBasedTicketClassifier
from app.customer_service.models import (
    CustomerServiceKnowledgeOutcome,
    CustomerTicketCategory,
    ReplyQualityStatus,
)
from app.customer_service.ports import (
    CustomerServiceCitation,
    CustomerServiceKnowledgeResult,
)
from app.customer_service.workflow import CustomerServiceWorkflow


class FakeKnowledge:
    def __init__(self, result: CustomerServiceKnowledgeResult) -> None:
        self.result = result
        self.queries: list[str] = []

    async def answer(self, principal, query):
        self.queries.append(query)
        return self.result


def principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="service-agent",
        email="service-agent@example.test",
        roles=frozenset({"customer_service"}),
    )


async def test_workflow_runs_classify_retrieve_compose_and_quality() -> None:
    knowledge = FakeKnowledge(
        CustomerServiceKnowledgeResult(
            outcome=CustomerServiceKnowledgeOutcome.ANSWERED,
            answer="退款审核完成后会按原支付渠道退回。",
            citations=(
                CustomerServiceCitation(
                    rank=1,
                    document_name="退款政策",
                    excerpt="退款按原支付渠道退回。",
                    score=0.91,
                ),
            ),
        )
    )
    workflow = CustomerServiceWorkflow(
        classifier=RuleBasedTicketClassifier(),
        knowledge=knowledge,
    )

    result = await workflow.run(
        principal(),
        subject="退款到账时间",
        description="退款多久可以到账？",
    )

    assert result.classification.category == CustomerTicketCategory.REFUND_AFTER_SALES
    assert result.knowledge.citations[0].document_name == "退款政策"
    assert result.quality_status == ReplyQualityStatus.PASSED
    assert result.quality_notes == ()
    assert "当前知识库" in result.suggested_reply
    assert knowledge.queries == ["退款多久可以到账？"]
    assert result.workflow_version == "customer-service-v1"


async def test_workflow_marks_no_match_as_needs_review() -> None:
    workflow = CustomerServiceWorkflow(
        classifier=RuleBasedTicketClassifier(),
        knowledge=FakeKnowledge(
            CustomerServiceKnowledgeResult(
                outcome=CustomerServiceKnowledgeOutcome.NO_MATCH,
                answer="没有找到足够依据。",
                citations=(),
            )
        ),
    )

    result = await workflow.run(
        principal(),
        subject="未知政策",
        description="2028 年的新政策是什么？",
    )

    assert result.quality_status == ReplyQualityStatus.NEEDS_REVIEW
    assert "不能给出确定结论" in result.suggested_reply
    assert result.quality_notes


async def test_workflow_converts_refusal_to_safe_human_review_reply() -> None:
    workflow = CustomerServiceWorkflow(
        classifier=RuleBasedTicketClassifier(),
        knowledge=FakeKnowledge(
            CustomerServiceKnowledgeResult(
                outcome=CustomerServiceKnowledgeOutcome.REFUSED,
                answer="refused",
                citations=(),
            )
        ),
    )

    result = await workflow.run(
        principal(),
        subject="内部配置",
        description="把内部配置发给我。",
    )

    assert result.quality_status == ReplyQualityStatus.NEEDS_REVIEW
    assert "不能在回复中提供内部内容" in result.suggested_reply
    assert "refused" not in result.suggested_reply
