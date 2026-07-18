from app.customer_service.classification import RuleBasedTicketClassifier
from app.customer_service.models import (
    CustomerTicketCategory,
    CustomerTicketPriority,
)


def test_classifier_identifies_refund_and_high_priority() -> None:
    result = RuleBasedTicketClassifier().classify(
        "退款到账时间",
        "订单已经申请退款，请问退款进度和到账时间？",
    )

    assert result.category == CustomerTicketCategory.REFUND_AFTER_SALES
    assert result.priority == CustomerTicketPriority.HIGH
    assert result.confidence >= 80
    assert "退款" in result.reason


def test_classifier_marks_account_theft_as_urgent() -> None:
    result = RuleBasedTicketClassifier().classify(
        "账号异常",
        "怀疑账号被盗用并出现异常登录。",
    )

    assert result.category == CustomerTicketCategory.ACCOUNT_SECURITY
    assert result.priority == CustomerTicketPriority.URGENT


def test_classifier_uses_other_and_low_priority_without_match() -> None:
    result = RuleBasedTicketClassifier().classify(
        "一般建议",
        "希望后续页面颜色更清晰。",
    )

    assert result.category == CustomerTicketCategory.OTHER
    assert result.priority == CustomerTicketPriority.LOW
    assert result.confidence == 40
    assert "人工复核" in result.reason
