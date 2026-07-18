import re

from app.customer_service.models import (
    CustomerTicketCategory,
    CustomerTicketPriority,
)
from app.customer_service.ports import TicketClassification


_CATEGORY_RULES: tuple[tuple[CustomerTicketCategory, tuple[str, ...]], ...] = (
    (
        CustomerTicketCategory.REFUND_AFTER_SALES,
        ("退款", "退货", "售后", "到账", "撤销订单", "退款进度"),
    ),
    (
        CustomerTicketCategory.ACCOUNT_SECURITY,
        ("账号", "账户", "登录", "密码", "验证码", "隐私", "安全", "盗用"),
    ),
    (
        CustomerTicketCategory.PRODUCT_SERVICE,
        ("产品", "套餐", "价格", "费用", "服务内容", "购买", "续费"),
    ),
    (
        CustomerTicketCategory.KNOWLEDGE_DOCUMENT,
        ("知识库", "文档", "上传", "pdf", "docx", "检索", "索引"),
    ),
    (
        CustomerTicketCategory.TECHNICAL_SUPPORT,
        ("报错", "故障", "异常", "无法使用", "打不开", "超时", "连接失败"),
    ),
)

_CATEGORY_LABELS = {
    CustomerTicketCategory.REFUND_AFTER_SALES: "退款与售后",
    CustomerTicketCategory.ACCOUNT_SECURITY: "账户安全",
    CustomerTicketCategory.PRODUCT_SERVICE: "产品与服务",
    CustomerTicketCategory.KNOWLEDGE_DOCUMENT: "知识库与文档",
    CustomerTicketCategory.TECHNICAL_SUPPORT: "技术支持",
    CustomerTicketCategory.OTHER: "其他",
}

_URGENT_TERMS = ("盗用", "泄露", "诈骗", "异常登录", "资金损失")
_HIGH_TECHNICAL_TERMS = ("无法使用", "打不开", "服务中断", "连接失败")


class RuleBasedTicketClassifier:
    def classify(self, subject: str, description: str) -> TicketClassification:
        normalized = re.sub(r"\s+", " ", f"{subject} {description}").casefold()
        best_category = CustomerTicketCategory.OTHER
        best_terms: tuple[str, ...] = ()

        for category, terms in _CATEGORY_RULES:
            matched = tuple(term for term in terms if term.casefold() in normalized)
            if len(matched) > len(best_terms):
                best_category = category
                best_terms = matched

        priority = self._priority(normalized, best_category)
        if best_terms:
            confidence = min(95, 70 + len(best_terms) * 10)
            reason = (
                f"命中{_CATEGORY_LABELS[best_category]}相关关键词："
                f"{'、'.join(best_terms[:4])}。"
            )
        else:
            confidence = 40
            reason = "未命中稳定业务关键词，暂归入其他类别并需要人工复核。"

        return TicketClassification(
            category=best_category,
            priority=priority,
            confidence=confidence,
            reason=reason[:500],
        )

    @staticmethod
    def _priority(
        normalized: str,
        category: CustomerTicketCategory,
    ) -> CustomerTicketPriority:
        if any(term in normalized for term in _URGENT_TERMS):
            return CustomerTicketPriority.URGENT
        if category in {
            CustomerTicketCategory.REFUND_AFTER_SALES,
            CustomerTicketCategory.ACCOUNT_SECURITY,
        }:
            return CustomerTicketPriority.HIGH
        if category == CustomerTicketCategory.TECHNICAL_SUPPORT and any(
            term in normalized for term in _HIGH_TECHNICAL_TERMS
        ):
            return CustomerTicketPriority.HIGH
        if category == CustomerTicketCategory.OTHER:
            return CustomerTicketPriority.LOW
        return CustomerTicketPriority.NORMAL
