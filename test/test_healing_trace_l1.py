# test/test_healing_trace_l1.py
"""
L1 纯函数测试：summarize_self_healing_trace。零依赖、不连网。
把自愈叙事的核心固化成回归——是否自愈、V4 0-LLM 短路、LLM 降级、熔断、中文映射。
"""
from utils.healing_trace import summarize_self_healing_trace


# 复用的样例 trace 片段
TOOLS_ERROR = {"node": "tools", "tool_name": "book_seat_tool", "status": "error"}
TOOLS_OK = {"node": "tools", "tool_name": "search_free_seats_tool", "status": "success"}
AGENT_RESPOND = {"node": "booking_agent", "decision": "respond_to_user", "tools_called": []}
SHORTCUT = {
    "node": "error_analyzer", "decision": "shortcut_via_metadata",
    "category": "resource_conflict", "user_summary": "座位已被占用", "llm_called": False,
}
LLM_CLASSIFY = {
    "node": "error_analyzer", "decision": "classified_by_llm",
    "category": "invalid_params", "reasoning": "时长越界",
    "user_summary": "时长不合法", "llm_called": True,
}
CIRCUIT = {"node": "error_analyzer", "decision": "circuit_breaker_triggered"}


class TestNoHealing:

    def test_empty_trace(self):
        s = summarize_self_healing_trace([])
        assert s["healing_triggered"] is False
        assert s["steps"] == []
        assert s["shortcut_count"] == 0

    def test_none_trace(self):
        s = summarize_self_healing_trace(None)
        assert s["healing_triggered"] is False

    def test_normal_turn_no_error(self):
        """正常一轮（只有主控回复）→ 不算自愈，无步骤。"""
        s = summarize_self_healing_trace([
            {"node": "booking_agent", "decision": "call_tools", "tools_called": ["search_free_seats_tool"]},
            TOOLS_OK,
            AGENT_RESPOND,
        ])
        assert s["healing_triggered"] is False
        assert s["steps"] == []


class TestShortcutPath:

    def test_v4_shortcut(self):
        """⭐ V4 0-LLM 短路：tools error + shortcut → 短路计数，无 LLM 调用。"""
        s = summarize_self_healing_trace([TOOLS_ERROR, SHORTCUT, AGENT_RESPOND])
        assert s["healing_triggered"] is True
        assert s["shortcut_count"] == 1
        assert s["llm_classify_calls"] == 0
        # 步骤：🔧 工具错误 → ⚡ 短路分类
        assert [step["icon"] for step in s["steps"]] == ["🔧", "⚡"]
        assert "资源冲突" in s["steps"][1]["title"]       # 中文映射
        assert "0 次 LLM 调用" in s["steps"][1]["title"]   # 0-LLM 铁证
        assert s["steps"][1]["detail"] == "座位已被占用"

    def test_tool_name_in_step(self):
        s = summarize_self_healing_trace([TOOLS_ERROR, SHORTCUT])
        assert "book_seat_tool" in s["steps"][0]["title"]


class TestLLMFallbackPath:

    def test_llm_classify(self):
        s = summarize_self_healing_trace([TOOLS_ERROR, LLM_CLASSIFY])
        assert s["healing_triggered"] is True
        assert s["llm_classify_calls"] == 1
        assert s["shortcut_count"] == 0
        assert s["steps"][1]["icon"] == "🧠"
        assert "参数不合法" in s["steps"][1]["title"]
        assert s["steps"][1]["detail"] == "时长越界"  # reasoning 优先


class TestCircuitBreaker:

    def test_circuit_broken(self):
        s = summarize_self_healing_trace([TOOLS_ERROR, SHORTCUT, TOOLS_ERROR, CIRCUIT])
        assert s["circuit_broken"] is True
        assert s["healing_triggered"] is True
        # 末步是熔断
        assert s["steps"][-1]["icon"] == "🔥"


class TestRobustness:

    def test_category_cn_mapping_all(self):
        for code, cn in [
            ("business_rule_violation", "业务规则拒绝"),
            ("resource_conflict", "资源冲突"),
            ("invalid_params", "参数不合法"),
            ("transient_failure", "瞬态故障"),
            ("unrecoverable", "不可恢复错误"),
        ]:
            entry = {"node": "error_analyzer", "decision": "shortcut_via_metadata",
                     "category": code, "user_summary": ""}
            s = summarize_self_healing_trace([entry])
            assert cn in s["steps"][0]["title"]

    def test_unknown_category_passthrough(self):
        entry = {"node": "error_analyzer", "decision": "shortcut_via_metadata",
                 "category": "some_new_code", "user_summary": ""}
        s = summarize_self_healing_trace([entry])
        assert "some_new_code" in s["steps"][0]["title"]

    def test_non_dict_entries_skipped(self):
        s = summarize_self_healing_trace([TOOLS_ERROR, "garbage", None, SHORTCUT])
        assert s["healing_triggered"] is True
        assert len(s["steps"]) == 2

    def test_order_preserved_multi_attempt(self):
        """两轮自愈（短路 + 降级混合）→ 计数正确、步骤有序。"""
        s = summarize_self_healing_trace([TOOLS_ERROR, SHORTCUT, TOOLS_ERROR, LLM_CLASSIFY])
        assert s["shortcut_count"] == 1
        assert s["llm_classify_calls"] == 1
        assert [step["icon"] for step in s["steps"]] == ["🔧", "⚡", "🔧", "🧠"]