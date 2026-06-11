# tests/test_self_healing_l1.py
"""
L1 纯函数测试：零依赖、不 mock、不连网。
覆盖 Self-Healing 的确定性部分——策略表、枚举一致性、正则提取、安全模板。
这些是 V4 短路路径的命脉，必须有回归保护。
"""
import pytest

from schemas.exceptions import ErrorCategory
from graphs.booking_self_healing_subgraph import (
    REPAIR_STRATEGY_MAP,
    _ERROR_CATEGORY_PATTERN,
    _ERROR_MESSAGE_PATTERN,
)

# 所有合法 category（与 ErrorCategory 枚举值对齐）
ALL_CATEGORIES = {c.value for c in ErrorCategory}
# 语义上"不应重试"的两类
NO_RETRY_CATEGORIES = {"business_rule_violation", "unrecoverable"}


# ==========================================
# 1. 策略表完备性
# ==========================================
class TestStrategyMapCompleteness:

    def test_all_categories_have_strategy(self):
        """每个 ErrorCategory 枚举值都必须在策略表里有条目（防漏配）。"""
        missing = ALL_CATEGORIES - set(REPAIR_STRATEGY_MAP.keys())
        assert not missing, f"以下 category 缺少修复策略: {missing}"

    def test_no_extra_strategy_keys(self):
        """策略表里不应有 ErrorCategory 之外的野键（防拼写错误）。"""
        extra = set(REPAIR_STRATEGY_MAP.keys()) - ALL_CATEGORIES
        assert not extra, f"策略表存在未知 category 键: {extra}"

    # 有了这个装饰器，pytest 会在后台自动把这 1 个测试方法裂变成 5 个独立的测试用例。
    # 它会把列表里的值，逐一赋给变量 "category"，然后分别运行。这 5 次运行互不干扰，终端里也会清晰地打印出 5 行测试结果。
    @pytest.mark.parametrize("category", sorted(ALL_CATEGORIES))
    def test_strategy_shape(self, category):
        """每条策略必须含 should_retry(bool) 和 instruction_template(非空 str)。"""
        strategy = REPAIR_STRATEGY_MAP[category]
        assert isinstance(strategy["should_retry"], bool)
        assert isinstance(strategy["instruction_template"], str)
        assert strategy["instruction_template"].strip(), "instruction_template 不能为空"

    @pytest.mark.parametrize("category", sorted(ALL_CATEGORIES))
    def test_should_retry_semantics(self, category):
        """should_retry 取值符合语义：业务拒绝/不可恢复不重试，其余可重试。"""

        # 这一行是在计算“标准答案”（expected）
        # NO_RETRY_CATEGORIES 是我们在文件顶部定义的集合，包含不需要重试的类
        # 如果当前的 category 不在这个集合里，说明它应该重试，expected 就是 True。
        # 如果它在这个集合里，说明它不该重试，expected 就是 False。
        expected = category not in NO_RETRY_CATEGORIES

        # 将字典里实际配置的值，和我们刚刚计算的标准答案进行对比。必须完全一致才算通过。
        assert REPAIR_STRATEGY_MAP[category]["should_retry"] is expected


# ==========================================
# 2. 正则提取（V4 短路命脉）
# ==========================================
class TestErrorParsing:

    def test_extract_category_known(self):
        """标准 [TOOL_ERROR] 串能提取出 category。"""
        text = "[TOOL_ERROR] category=resource_conflict, error_code=SEAT_OCCUPIED, message=座位已被占用"
        m = _ERROR_CATEGORY_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "resource_conflict"

    @pytest.mark.parametrize("category", sorted(ALL_CATEGORIES))
    def test_extract_every_category(self, category):
        """5 类 category 都能被正则正确提取。"""
        text = f"[TOOL_ERROR] category={category}, error_code=X, message=测试消息"
        m = _ERROR_CATEGORY_PATTERN.search(text)
        assert m is not None and m.group(1) == category

    def test_extract_category_absent_returns_none(self):
        """不带 category 的错误串 → 提取不到 → 触发 LLM 降级路径。"""
        text = "[TOOL_ERROR] error_code=NO_AUTH, message=未认证用户禁止调用工具"
        assert _ERROR_CATEGORY_PATTERN.search(text) is None

    def test_extract_message(self):
        """能从错误串里提取 message 文本（填充 user_summary 用）。"""
        text = "[TOOL_ERROR] category=invalid_params, error_code=INVALID_PARAM, message=时长必须在 1 到 8 小时之间"
        m = _ERROR_MESSAGE_PATTERN.search(text)
        assert m is not None
        assert "时长必须在 1 到 8 小时之间" in m.group(1)

    def test_parsed_category_is_valid_strategy_key(self):
        """从真实错误串提取的 category 必须能直接命中策略表（端到端短路验证）。"""
        text = "[TOOL_ERROR] category=unrecoverable, error_code=NOT_YOUR_BOOKING, message=操作无法完成"
        category = _ERROR_CATEGORY_PATTERN.search(text).group(1)
        assert category in REPAIR_STRATEGY_MAP


# ==========================================
# 3. unrecoverable 模板安全性（把"静默不泄露"固化成测试）
# ==========================================
class TestUnrecoverableTemplateSafety:

    def test_template_forbids_sensitive_disclosure(self):
        """unrecoverable 模板必须含禁止泄露敏感信息的约束词。"""
        tmpl = REPAIR_STRATEGY_MAP["unrecoverable"]["instruction_template"]
        # 必须明确禁止提及这些敏感字段
        for keyword in ["booking_id", "座位号", "错误码"]:
            assert keyword in tmpl, f"unrecoverable 模板应明确禁止泄露『{keyword}』"

    def test_template_forbids_tool_retry(self):
        """unrecoverable 模板必须禁止再调用工具。"""
        tmpl = REPAIR_STRATEGY_MAP["unrecoverable"]["instruction_template"]
        assert "禁止" in tmpl and "工具" in tmpl