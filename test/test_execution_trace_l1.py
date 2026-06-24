# test/test_execution_trace_l1.py
"""
L1 纯函数测试：summarize_execution_trace。零依赖、不连网。
覆盖执行轨迹的核心叙事——工具调用可见、成败、V4 0-LLM 短路、LLM 降级、熔断。
"""
from utils.execution_trace import summarize_execution_trace


TOOLS_OK = {"node": "tools", "tool_name": "book_seat_tool", "status": "success"}
TOOLS_OK2 = {"node": "tools", "tool_name": "search_free_seats_tool", "status": "success"}
TOOLS_ERR = {"node": "tools", "tool_name": "book_seat_tool", "status": "error"}
NO_AUTH = {"node": "tools", "decision": "no_auth_abort"}  # 无 status
AGENT_CALL = {"node": "booking_agent", "decision": "call_tools", "tools_called": ["book_seat_tool"]}
AGENT_RESPOND = {"node": "booking_agent", "decision": "respond_to_user", "tools_called": []}
SHORTCUT = {
    "node": "error_analyzer", "decision": "shortcut_via_metadata",
    "category": "resource_conflict", "user_summary": "座位已被占用", "llm_called": False,
}
LLM_CLASSIFY = {
    "node": "error_analyzer", "decision": "classified_by_llm",
    "category": "invalid_params", "reasoning": "时长越界", "user_summary": "时长不合法",
}
CIRCUIT = {"node": "error_analyzer", "decision": "circuit_breaker_triggered"}


class TestNoActivity:

    def test_empty(self):
        s = summarize_execution_trace([])
        assert s["has_activity"] is False
        assert s["steps"] == []
        assert s["tool_call_count"] == 0

    def test_none(self):
        assert summarize_execution_trace(None)["has_activity"] is False

    def test_pure_conversation(self):
        """纯对话（只有主控回复，无工具）→ 无活动，不显示面板。"""
        s = summarize_execution_trace([AGENT_RESPOND])
        assert s["has_activity"] is False
        assert s["steps"] == []


class TestToolVisibility:

    def test_single_success(self):
        """⭐ 一次成功工具调用 → 可见，无自愈。"""
        s = summarize_execution_trace([AGENT_CALL, TOOLS_OK, AGENT_RESPOND])
        assert s["has_activity"] is True
        assert s["tool_call_count"] == 1
        assert s["healing_triggered"] is False
        assert s["steps"][0]["icon"] == "▸"
        assert "book_seat_tool" in s["steps"][0]["title"]
        assert "✓" in s["steps"][0]["title"]

    def test_no_auth_abort_not_counted(self):
        """无 status 的 tools 记录（no_auth_abort）不计入工具调用。"""
        s = summarize_execution_trace([NO_AUTH])
        assert s["tool_call_count"] == 0
        assert s["has_activity"] is False

    def test_call_tools_not_double_counted(self):
        """booking_agent 的 call_tools 不重复计数（工具名以 tools 记录为准）。"""
        s = summarize_execution_trace([AGENT_CALL, TOOLS_OK])
        assert s["tool_call_count"] == 1  # 只算 1 次，不因 AGENT_CALL 翻倍
        assert len(s["steps"]) == 1


class TestHealingWithTools:

    def test_error_then_shortcut(self):
        """⭐ 工具失败 → 短路自愈：工具步可见(✕) + 短路分类，0 LLM。"""
        s = summarize_execution_trace([AGENT_CALL, TOOLS_ERR, SHORTCUT])
        assert s["has_activity"] is True
        assert s["tool_call_count"] == 1
        assert s["healing_triggered"] is True
        assert s["shortcut_count"] == 1
        assert s["llm_classify_calls"] == 0
        # 步骤：▸ 失败 → ◆ 短路分类
        assert [step["icon"] for step in s["steps"]] == ["▸", "◆"]
        assert "✕" in s["steps"][0]["title"]
        assert "资源冲突" in s["steps"][1]["title"]
        assert "0 次 LLM 调用" in s["steps"][1]["title"]

    def test_heal_then_retry_success(self):
        """⭐ 失败→短路→二次调用成功：tool_call_count=2，全程可见。"""
        s = summarize_execution_trace([
            AGENT_CALL, TOOLS_ERR, SHORTCUT, AGENT_CALL, TOOLS_OK2, AGENT_RESPOND
        ])
        assert s["tool_call_count"] == 2
        assert [step["icon"] for step in s["steps"]] == ["▸", "◆", "▸"]
        assert "search_free_seats_tool" in s["steps"][2]["title"]
        assert "✓" in s["steps"][2]["title"]

    def test_llm_fallback(self):
        s = summarize_execution_trace([TOOLS_ERR, LLM_CLASSIFY])
        assert s["llm_classify_calls"] == 1
        assert s["shortcut_count"] == 0
        assert s["steps"][1]["icon"] == "◇"
        assert "参数不合法" in s["steps"][1]["title"]
        assert s["steps"][1]["detail"] == "时长越界"

    def test_circuit_breaker(self):
        s = summarize_execution_trace([TOOLS_ERR, SHORTCUT, TOOLS_ERR, CIRCUIT])
        assert s["circuit_broken"] is True
        assert s["tool_call_count"] == 2
        assert s["steps"][-1]["icon"] == "⊘"


class TestRobustness:

    def test_category_cn_all(self):
        for code, cn in [
            ("business_rule_violation", "业务规则拒绝"),
            ("resource_conflict", "资源冲突"),
            ("invalid_params", "参数不合法"),
            ("transient_failure", "瞬态故障"),
            ("unrecoverable", "不可恢复错误"),
        ]:
            s = summarize_execution_trace([
                {"node": "error_analyzer", "decision": "shortcut_via_metadata",
                 "category": code, "user_summary": ""}
            ])
            assert cn in s["steps"][0]["title"]

    def test_unknown_category_passthrough(self):
        s = summarize_execution_trace([
            {"node": "error_analyzer", "decision": "shortcut_via_metadata",
             "category": "new_code", "user_summary": ""}
        ])
        assert "new_code" in s["steps"][0]["title"]

    def test_non_dict_skipped(self):
        s = summarize_execution_trace([TOOLS_OK, "junk", None, TOOLS_ERR, SHORTCUT])
        assert s["tool_call_count"] == 2
        assert len(s["steps"]) == 3

    def test_order_preserved(self):
        s = summarize_execution_trace([TOOLS_ERR, SHORTCUT, TOOLS_OK2])
        assert [step["icon"] for step in s["steps"]] == ["▸", "◆", "▸"]