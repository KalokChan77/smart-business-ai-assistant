import ast
import json
import math
import operator
from typing import Literal

from langchain.tools import tool

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_MAX_EXPRESSION_LENGTH = 200
_MAX_ABSOLUTE_RESULT = 1_000_000_000_000

_DEMO_POLICIES = {
    "refund": {
        "title": "模拟退款政策",
        "content": "订单支付后 7 天内且服务未开始时可申请退款，特殊商品以合同约定为准。",
    },
    "account_security": {
        "title": "模拟账户安全政策",
        "content": "账户异常时应先修改密码、退出其他设备，并联系管理员核验操作记录。",
    },
    "product_plan": {
        "title": "模拟产品套餐政策",
        "content": "基础版适合小团队，专业版增加知识库和客服辅助，企业版支持定制集成。",
    },
}


class UnsafeExpressionError(ValueError):
    pass


def evaluate_expression(expression: str) -> int | float:
    normalized = expression.strip()
    if not normalized or len(normalized) > _MAX_EXPRESSION_LENGTH:
        raise UnsafeExpressionError("表达式为空或长度超限。")
    try:
        root = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError("表达式格式不正确。") from exc
    result = _evaluate_node(root.body)
    if not math.isfinite(float(result)) or abs(result) > _MAX_ABSOLUTE_RESULT:
        raise UnsafeExpressionError("计算结果超出允许范围。")
    return result


def _evaluate_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise UnsafeExpressionError("只允许数字常量。")
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise UnsafeExpressionError("幂指数超出允许范围。")
        try:
            return _BINARY_OPERATORS[type(node.op)](left, right)
        except (ArithmeticError, OverflowError) as exc:
            raise UnsafeExpressionError("表达式无法安全计算。") from exc
    raise UnsafeExpressionError("表达式包含不允许的语法。")


@tool
def calculate_business_metric(expression: str) -> str:
    """安全计算只包含数字、括号和基本运算符的算术表达式。"""
    result = evaluate_expression(expression)
    return json.dumps(
        {"expression": expression, "result": result},
        ensure_ascii=False,
        separators=(",", ":"),
    )


@tool
def lookup_demo_business_policy(
    topic: Literal["refund", "account_security", "product_plan"],
) -> str:
    """查询教学项目内置的模拟退款、账户安全或产品套餐政策。"""
    return json.dumps(
        {"topic": topic, **_DEMO_POLICIES[topic], "source": "demo_policy"},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def registered_tools():
    return (calculate_business_metric, lookup_demo_business_policy)
