# test/test_self_healing_l2.py
"""
L2 异步 mock 测试：验证 analyze_error 的决策路径。
核心命题——用 mock 的调用计数证明：
  · V4 短路路径下 LLM 零调用（项目最核心的设计主张）
  · 熔断触发时 LLM 零调用
  · 仅未知异常才降级到 LLM
不连网、不连 MCP、不需要 API key。
"""
import pytest
from langchain_core.messages import ToolMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from graphs.booking_self_healing_subgraph import (
    analyze_error,
    ErrorClassification,
    MAX_REPAIR_ATTEMPTS,
)


# ==========================================
# Fake LLM：记录 with_structured_output 调用次数
# ==========================================
class _FakeLLM:
    """
    伪 LLM。with_structured_output 返回一个真正的 Runnable（RunnableLambda），
    以便正确接入 analyze_error 里的 `prompt | structured_llm` 管道。
    structured_output_call_count 用于断言 LLM 是否被调用。
    """
    def __init__(self, classification: ErrorClassification = None):
        self._classification = classification
        self.structured_output_call_count = 0

    def with_structured_output(self, schema):
        self.structured_output_call_count += 1

        async def _return_fixed(_input):
            return self._classification

        return RunnableLambda(_return_fixed)


def _tool_error_state(
    error_content: str,
    repair_attempts: int = 0,
    artifact: dict = None,
) -> dict:
    """
    构造最小 AgentState：含一条带 [TOOL_ERROR] 的 ToolMessage。

    artifact 参数（重构后新增）：
    - 传 dict → ToolMessage 带 artifact，analyze_error 走 artifact 优先路径
    - 不传 → 无 artifact，analyze_error 回退到正则解析 content（兼容遗留路径）
    """
    return {
        "messages": [
            HumanMessage(content="取消订单 BKG_TEST0002"),
            ToolMessage(
                content=error_content,
                name="cancel_booking_tool",
                tool_call_id="t:0",
                artifact=artifact,  # None 或 dict
            ),
        ],
        "repair_attempts": repair_attempts,
        "current_user_intent": "取消订单 BKG_TEST0002",
    }


# ==========================================
# 组 1：V4 短路 —— 0 LLM 调用（最核心）
# ==========================================
class TestV4Shortcut:

    @pytest.mark.asyncio
    async def test_known_category_zero_llm_call(self):
        """带 category 的已知异常 → 短路查表，LLM 绝不被调用。"""
        state = _tool_error_state(
            "[TOOL_ERROR] category=unrecoverable, error_code=NOT_YOUR_BOOKING, message=操作无法完成"
        )
        fake_llm = _FakeLLM()  # 不预设分类——因为根本不该用到

        result = await analyze_error(state, fake_llm)

        # ⭐ 铁证：LLM 零调用
        assert fake_llm.structured_output_call_count == 0
        trace = result["trace"][0]
        assert trace["decision"] == "shortcut_via_metadata"
        assert trace["category"] == "unrecoverable"
        assert trace["llm_called"] is False

    @pytest.mark.asyncio
    async def test_resource_conflict_shortcut(self):
        """resource_conflict 也走短路，且 user_summary 来自错误报文 message。"""
        state = _tool_error_state(
            "[TOOL_ERROR] category=resource_conflict, error_code=SEAT_OCCUPIED, message=座位 5 当前已被占用"
        )
        fake_llm = _FakeLLM()

        result = await analyze_error(state, fake_llm)

        assert fake_llm.structured_output_call_count == 0
        assert result["trace"][0]["category"] == "resource_conflict"
        # 短路路径从 message 提取 user_summary 填进指令
        assert "座位 5 当前已被占用" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_shortcut_increments_repair_attempts(self):
        """短路路径也要 +1 自愈计数（熔断依赖它）。"""
        state = _tool_error_state(
            "[TOOL_ERROR] category=invalid_params, error_code=INVALID_PARAM, message=时长越界",
            repair_attempts=0,
        )
        result = await analyze_error(state, _FakeLLM())
        assert result["repair_attempts"] == 1

    @pytest.mark.asyncio
    async def test_artifact_preferred_over_content(self):
        """⭐ artifact 优先：有 artifact 时，category 从 artifact 读，不依赖 content 字符串。"""
        # 故意让 content 里的字符串"撒谎"（写成 invalid_params），
        # 但 artifact 里是真实的 unrecoverable —— 验证读的是 artifact 而非 content
        state = _tool_error_state(
            error_content="[TOOL_ERROR] category=invalid_params, error_code=X, message=诱饵",
            artifact={
                "is_error": True,
                "category": "unrecoverable",
                "error_code": "NOT_YOUR_BOOKING",
                "message": "操作无法完成",
            },
        )
        result = await analyze_error(state, _FakeLLM())

        # 应采信 artifact 的 unrecoverable，而非 content 字符串的 invalid_params
        assert result["trace"][0]["category"] == "unrecoverable"
        assert result["trace"][0]["llm_called"] is False
        # user_summary 也应来自 artifact 的 message
        assert "操作无法完成" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_artifact_message_fills_user_summary(self):
        """artifact 的 message 字段填充 user_summary（短路路径）。"""
        state = _tool_error_state(
            error_content="[TOOL_ERROR] category=resource_conflict, error_code=SEAT_OCCUPIED, message=x",
            artifact={
                "is_error": True,
                "category": "resource_conflict",
                "error_code": "SEAT_OCCUPIED",
                "message": "座位 5 当前已被占用",
            },
        )
        result = await analyze_error(state, _FakeLLM())
        assert "座位 5 当前已被占用" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_string_fallback_when_no_artifact(self):
        """⭐ 回退兼容：无 artifact 时（如 NO_AUTH 遗留路径），仍能正则解析 content。"""
        state = _tool_error_state(
            error_content="[TOOL_ERROR] category=transient_failure, error_code=DB_SYSTEM_ERROR, message=数据库抖动",
            artifact=None,  # 显式无 artifact
        )
        result = await analyze_error(state, _FakeLLM())
        # 回退到正则，仍能正确短路
        assert result["trace"][0]["category"] == "transient_failure"
        assert result["trace"][0]["llm_called"] is False

# ==========================================
# 组 2：熔断
# ==========================================
class TestCircuitBreaker:

    @pytest.mark.asyncio
    async def test_circuit_breaker_triggers_at_threshold(self):
        """repair_attempts 达到阈值 → 走熔断分支，LLM 零调用。"""
        state = _tool_error_state(
            "[TOOL_ERROR] category=transient_failure, error_code=DB_SYSTEM_ERROR, message=数据库抖动",
            repair_attempts=MAX_REPAIR_ATTEMPTS,  # 已达上限
        )
        fake_llm = _FakeLLM()

        result = await analyze_error(state, fake_llm)

        assert fake_llm.structured_output_call_count == 0
        assert result["trace"][0]["decision"] == "circuit_breaker_triggered"
        # 熔断指令必须禁止再调工具
        assert "禁止" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_below_threshold_does_not_break(self):
        """未达阈值 → 正常走短路，不熔断。"""
        state = _tool_error_state(
            "[TOOL_ERROR] category=transient_failure, error_code=DB_SYSTEM_ERROR, message=数据库抖动",
            repair_attempts=MAX_REPAIR_ATTEMPTS - 1,
        )
        result = await analyze_error(state, _FakeLLM())
        assert result["trace"][0]["decision"] != "circuit_breaker_triggered"

    @pytest.mark.asyncio
    async def test_custom_max_attempts(self):
        """阈值可注入：max_attempts=1 时，repair_attempts=1 即熔断。"""
        state = _tool_error_state(
            "[TOOL_ERROR] category=invalid_params, error_code=X, message=y",
            repair_attempts=1,
        )
        result = await analyze_error(state, _FakeLLM(), max_attempts=1)
        assert result["trace"][0]["decision"] == "circuit_breaker_triggered"


# ==========================================
# 组 3：未知异常 → 降级 LLM
# ==========================================
class TestLLMFallback:

    @pytest.mark.asyncio
    async def test_unknown_error_falls_back_to_llm(self):
        """不带 category 的错误 → 降级调用 LLM 分类。"""
        # 预设 LLM 会把它分类成 unrecoverable
        fake_classification = ErrorClassification(
            reasoning="未认证，无法在会话内修复",
            category="unrecoverable",
            user_facing_summary="操作无法完成",
        )
        fake_llm = _FakeLLM(fake_classification)
        state = _tool_error_state(
            "[TOOL_ERROR] error_code=NO_AUTH, message=未认证用户禁止调用工具"  # 注意：无 category=
        )

        result = await analyze_error(state, fake_llm)

        # ⭐ LLM 被调用了恰好一次
        assert fake_llm.structured_output_call_count == 1
        trace = result["trace"][0]
        assert trace["decision"] == "classified_by_llm"
        assert trace["llm_called"] is True
        assert trace["category"] == "unrecoverable"

    @pytest.mark.asyncio
    async def test_llm_classified_resource_conflict_uses_strategy(self):
        """LLM 分类为 resource_conflict → 指令取自该类策略模板（含 user_summary）。"""
        fake_classification = ErrorClassification(
            reasoning="资源被占，换一个即可",
            category="resource_conflict",
            user_facing_summary="您选的座位暂时不可用",
        )
        fake_llm = _FakeLLM(fake_classification)
        state = _tool_error_state(
            "[TOOL_ERROR] error_code=WEIRD_UNKNOWN, message=底层未知错误"
        )

        result = await analyze_error(state, fake_llm)

        assert fake_llm.structured_output_call_count == 1
        # resource_conflict 策略会要求先查空座
        assert "search_free_seats_tool" in result["messages"][0].content
        # user_summary 被填进模板
        assert "您选的座位暂时不可用" in result["messages"][0].content