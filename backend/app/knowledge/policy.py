import re

_OVERRIDE_PATTERN = re.compile(
    r"(?:忽略|无视|绕过).{0,40}(?:规则|指令|限制|系统|之前)|"
    r"(?:ignore|bypass|override).{0,40}(?:rule|instruction|policy|system)",
    re.IGNORECASE,
)
_SENSITIVE_TERM = (
    r"系统提示词|系统指令|开发者指令|内部提示词|"
    r"内部配置|环境变量|配置文件|\.env\b|"
    r"api[\s_-]*key|access[\s_-]*token|refresh[\s_-]*token|jwt|"
    r"(?:dify[\s_-]*)?dataset[\s_-]*id|retrieval[\s_-]*model|"
    r"dify[\s_-]*(?:原始响应|原始字段|raw[\s_-]*response|raw[\s_-]*fields)|"
    r"cookie|密码|密钥|令牌|secret|password|system\s+prompt|"
    r"internal\s+config(?:uration)?|environment\s+variables?"
)
_DISCLOSURE_ACTION = (
    r"发给我|输出|显示|泄露|打印|返回给我|提供给我|告诉我|"
    r"reveal|show|print|expose|send\s+me|give\s+me|return"
)
_DISCLOSURE_PATTERN = re.compile(
    rf"(?:{_DISCLOSURE_ACTION}).{{0,40}}(?:{_SENSITIVE_TERM})|"
    rf"(?:{_SENSITIVE_TERM}).{{0,40}}(?:{_DISCLOSURE_ACTION})|"
    rf"(?:把|将).{{0,20}}(?:{_SENSITIVE_TERM}).{{0,30}}(?:{_DISCLOSURE_ACTION})",
    re.IGNORECASE,
)


class KnowledgeSafetyPolicy:
    """Recognize explicit prompt override and credential disclosure attempts."""

    def is_disclosure_attempt(self, query: str) -> bool:
        return bool(
            _OVERRIDE_PATTERN.search(query) or _DISCLOSURE_PATTERN.search(query)
        )
