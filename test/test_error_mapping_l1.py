# test/test_error_mapping_l1.py
"""L1 纯函数测试：_raise_from_result + _ERROR_MAP。

覆盖 MCP 结构化错误码 → 领域异常（带正确 category）的映射，
重点钉死 DB_ERROR → transient_failure（曾因码不匹配被误判为 unrecoverable）。
构造空 mcp_tools 的 BookingService，只测纯解析逻辑，不连真 MCP。
"""
import pytest

from services.booking_service import BookingService
from schemas.exceptions import (
    BookingDomainError, SystemBusyError, UserNotFoundError, ErrorCategory,
)


@pytest.fixture
def svc():
    return BookingService([])   # 空工具表，只测 _raise_from_result 纯逻辑


class TestErrorCodeMapping:

    def test_db_error_maps_to_transient_failure(self, svc):
        """⭐ 核心回归：DB_ERROR 必须落 transient_failure（可重试），而非 unrecoverable。"""
        with pytest.raises(SystemBusyError) as ei:
            svc._raise_from_result(
                {"success": False, "error_code": "DB_ERROR", "message": "db down"}
            )
        assert ei.value.category == ErrorCategory.TRANSIENT_FAILURE

    def test_user_not_found_maps_unrecoverable(self, svc):
        with pytest.raises(UserNotFoundError) as ei:
            svc._raise_from_result(
                {"success": False, "error_code": "USER_NOT_FOUND", "message": "查无此人"}
            )
        assert ei.value.category == ErrorCategory.UNRECOVERABLE

    def test_unknown_code_falls_back_to_base_domain_error(self, svc):
        with pytest.raises(BookingDomainError):
            svc._raise_from_result(
                {"success": False, "error_code": "WEIRD_CODE", "message": "x"}
            )

    def test_success_result_does_not_raise(self, svc):
        # success=True 直接放行，不抛
        svc._raise_from_result({"success": True})