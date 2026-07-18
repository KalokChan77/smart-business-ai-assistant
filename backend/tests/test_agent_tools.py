import pytest

from app.agent.tools import UnsafeExpressionError, evaluate_expression


def test_safe_expression_supports_basic_business_math() -> None:
    assert evaluate_expression("12 * 8 + 4") == 100
    assert evaluate_expression("(25 - 5) / 4") == 5


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo unsafe')",
        "value.attribute",
        "[1, 2, 3]",
        "2 ** 100",
        "10 / 0",
        "x + 1",
    ],
)
def test_safe_expression_rejects_dynamic_or_unbounded_syntax(
    expression: str,
) -> None:
    with pytest.raises(UnsafeExpressionError):
        evaluate_expression(expression)
