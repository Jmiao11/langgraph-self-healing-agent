# services/booking_service.py
import json

from schemas.exceptions import (
    SeatOccupiedError,
    ViolationLimitError,
    InvalidParamError,  # ⭐ 新增
    SystemBusyError,
    UserNotFoundError,  # ⭐ 新增
    BookingDomainError, SeatNotFoundError
)

class BookingService:
    def __init__(self, mcp_tools):
        # 接收原始 MCP 工具
        self.tools_map = {tool.name: tool for tool in mcp_tools}
        self.book_mcp = self.tools_map.get("book_seat_transaction")
        self.search_mcp = self.tools_map.get("search_free_seats")

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

        # 错误码 -> 异常类的映射表
        error_map = {
            "SEAT_OCCUPIED": SeatOccupiedError,
            "SEAT_NOT_FOUND": SeatNotFoundError,  # ⭐ 新增
            "VIOLATION_LIMIT": ViolationLimitError,
            "INVALID_PARAM": InvalidParamError,
            "DB_SYSTEM_ERROR": SystemBusyError,
            "USER_NOT_FOUND": UserNotFoundError,
        }

        exception_cls = error_map.get(error_code)
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