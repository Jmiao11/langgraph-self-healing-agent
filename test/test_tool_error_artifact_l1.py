# test/test_tool_error_artifact_l1.py
"""L1 纯函数测试：build_error_artifact。

覆盖工具执行异常 → (content, artifact) 的翻译：
  - 领域异常带自身 category（与下单/取消工具一致）
  - 裸异常兜底 transient_failure（进自愈链路、被熔断保护）
  - content 永远是纯友好文本，不泄露技术元数据 / 原始异常细节
零依赖、不连网、不需事件循环。
"""
from graphs.booking_self_healing_subgraph import (
    build_error_artifact,
    REPAIR_STRATEGY_MAP,
)
from schemas.exceptions import (
    BookingDomainError,
    SeatOccupiedError,
    SystemBusyError,
)


class TestDomainErrorMapping:

    def test_resource_conflict_maps_own_category(self):
        content, art = build_error_artifact(
            SeatOccupiedError("座位已被占用"), "FB", "fallback"
        )
        assert art["is_error"] is True
        assert art["category"] == "resource_conflict"
        assert art["error_code"] == "SEAT_OCCUPIED"
        # content = 纯友好文本，技术元数据不入 content
        assert content == "座位已被占用"
        assert "resource_conflict" not in content

    def test_base_domain_error_defaults_unrecoverable(self):
        _, art = build_error_artifact(
            BookingDomainError("MY_CODE", "自定义错误"), "FB", "fb"
        )
        assert art["category"] == "unrecoverable"
        assert art["error_code"] == "MY_CODE"

    def test_domain_error_ignores_fallback(self):
        """领域异常用自身 category/error_code/message，不取 fallback 参数。"""
        content, art = build_error_artifact(
            SystemBusyError("系统繁忙"), "FALLBACK_CODE", "fallback msg"
        )
        assert art["error_code"] == "DB_SYSTEM_ERROR"   # 自身的，非 fallback
        assert art["category"] == "transient_failure"
        assert content == "系统繁忙"


class TestBareExceptionFallback:

    def test_bare_exception_maps_transient(self):
        content, art = build_error_artifact(
            RuntimeError("MCP stdio broken"), "SEARCH_UNAVAILABLE", "查询暂不可用"
        )
        assert art["is_error"] is True
        assert art["category"] == "transient_failure"
        assert art["error_code"] == "SEARCH_UNAVAILABLE"
        assert content == "查询暂不可用"
        assert "MCP stdio broken" not in content   # 原始异常细节不泄露给用户

    def test_fallback_category_is_known_to_strategy_map(self):
        """兜底 category 必须是策略表已知分类，否则自愈链路接不住。"""
        _, art = build_error_artifact(ValueError("x"), "C", "m")
        assert art["category"] in REPAIR_STRATEGY_MAP