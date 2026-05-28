# services/booking_service.py
import json

from schemas.exceptions import (
    SeatOccupiedError,
    ViolationLimitError,
    InvalidParamError,
    SystemBusyError,
    UserNotFoundError,
    BookingDomainError,
    SeatNotFoundError,
    # ⭐ CRUD 扩展异常
    BookingNotFoundError,
    NotYourBookingError,
    BookingAlreadyCancelledError,
)

class BookingService:
    # ⭐ MCP error_code → Python 异常类的映射表
    # 提到类属性级别避免在每个方法里重复定义
    _ERROR_MAP = {
        "SEAT_OCCUPIED": SeatOccupiedError,
        "SEAT_NOT_FOUND": SeatNotFoundError,
        "VIOLATION_LIMIT": ViolationLimitError,
        "INVALID_PARAM": InvalidParamError,
        "DB_SYSTEM_ERROR": SystemBusyError,
        "USER_NOT_FOUND": UserNotFoundError,
        # ⭐ CRUD 扩展
        "BOOKING_NOT_FOUND": BookingNotFoundError,
        "NOT_YOUR_BOOKING": NotYourBookingError,
        "BOOKING_ALREADY_CANCELLED": BookingAlreadyCancelledError,
    }

    def __init__(self, mcp_tools):
        self.tools_map = {tool.name: tool for tool in mcp_tools}
        self.book_mcp = self.tools_map.get("book_seat_transaction")
        self.search_mcp = self.tools_map.get("search_free_seats")
        self.user_info_mcp = self.tools_map.get("get_user_info")
        # ⭐ CRUD 扩展工具
        self.get_my_bookings_mcp = self.tools_map.get("get_my_bookings")
        self.cancel_booking_mcp = self.tools_map.get("cancel_booking")
        self.update_booking_duration_mcp = self.tools_map.get("update_booking_duration")

    def _clean_mcp_output(self, raw_result) -> str:
        """专门负责处理 LangChain / MCP 恶心的多模态返回格式"""
        if isinstance(raw_result, list) and len(raw_result) > 0:
            first_item = raw_result[0]
            if isinstance(first_item, dict) and "text" in first_item:
                return first_item["text"]
            elif hasattr(first_item, "text"):
                return first_item.text
        return str(raw_result)

    async def book(self, student_id: str, seat_id: int, duration: int) -> dict:
        """
        纯粹的预定业务逻辑：成功返回数据字典，失败抛出明确的 Exception
        """
        raw_result = await self.book_mcp.ainvoke({
            "student_id": student_id,
            "seat_id": seat_id,
            "duration": duration
        })

        json_str = self._clean_mcp_output(raw_result)

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            raise SystemBusyError(f"底层返回非预期格式: {json_str}")

        if result.get("success"):
            return result.get("data", {})

        # 核心：将 JSON 错误码映射为 Python 标准异常
        error_code = result.get("error_code")
        msg = result.get("message", "未知错误")

        exception_cls = self._ERROR_MAP.get(error_code)
        if exception_cls:
            raise exception_cls(msg)

        # 未知错误码兜底为不可恢复
        raise BookingDomainError(error_code or "UNKNOWN", msg)


    async def search(self, zone_type: str = "") -> str:
        """查询空座的纯净方法"""
        # ⭐ 防御性编程：洗掉大模型传过来的 None
        args = {}
        # 只有当 zone_type 真的有文本内容时，我们才把这个键传给底层 MCP
        if zone_type is not None and str(zone_type).strip() != "":
            args["zone_type"] = str(zone_type).strip()

        # 如果 args 是空的 {}，FastMCP 那边会自动使用它自己的默认值，不会报错
        raw_result = await self.search_mcp.ainvoke(args)
        return self._clean_mcp_output(raw_result)

    async def get_user_info(self, student_id: str) -> str:
        """查询用户的积分和违约信息（纯净接口）"""
        raw_result = await self.user_info_mcp.ainvoke({"student_id": student_id})
        return self._clean_mcp_output(raw_result)

    # ==========================================
    # ⭐ CRUD 扩展方法：查询/取消/修改订单
    # ==========================================

    def _raise_from_result(self, result: dict) -> None:
        """统一的错误码 → Python 异常映射。
        若 result.success == False，根据 error_code 抛出对应的领域异常。
        若 success == True，方法直接返回（什么都不做）。
        """
        if result.get("success"):
            return
        error_code = result.get("error_code")
        msg = result.get("message", "未知错误")
        exception_cls = self._ERROR_MAP.get(error_code)
        if exception_cls:
            raise exception_cls(msg)
        raise BookingDomainError(error_code or "UNKNOWN", msg)

    async def get_my_bookings(self, student_id: str) -> list:
        """查询当前用户的所有订单。
        成功返回订单列表（list of dict），失败抛出 BookingDomainError。
        """
        raw_result = await self.get_my_bookings_mcp.ainvoke({"student_id": student_id})
        json_str = self._clean_mcp_output(raw_result)

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            raise SystemBusyError(f"底层返回非预期格式: {json_str}")

        self._raise_from_result(result)
        return result.get("data", [])

    async def cancel_booking(self, student_id: str, booking_id: str) -> dict:
        """取消订单（并释放座位）。
        成功返回操作详情字典，失败抛出对应的 BookingDomainError。
        """
        raw_result = await self.cancel_booking_mcp.ainvoke({
            "student_id": student_id,
            "booking_id": booking_id
        })
        json_str = self._clean_mcp_output(raw_result)

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            raise SystemBusyError(f"底层返回非预期格式: {json_str}")

        self._raise_from_result(result)
        return result.get("data", {})

    async def update_booking_duration(self, student_id: str, booking_id: str, new_duration: int) -> dict:
        """修改订单时长。
        成功返回操作详情字典，失败抛出对应的 BookingDomainError。
        """
        raw_result = await self.update_booking_duration_mcp.ainvoke({
            "student_id": student_id,
            "booking_id": booking_id,
            "new_duration": new_duration
        })
        json_str = self._clean_mcp_output(raw_result)

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            raise SystemBusyError(f"底层返回非预期格式: {json_str}")

        self._raise_from_result(result)
        return result.get("data", {})