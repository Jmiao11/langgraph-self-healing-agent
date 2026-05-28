# schemas/exceptions.py
from enum import Enum


class ErrorCategory(str, Enum):
    """
    错误语义分类：用于驱动 Self-Healing 的策略决策。

    设计原则：
    - 分类粒度对应 "处理策略" 的差异，而非错误本身的物理来源
    - 例如 SEAT_OCCUPIED 和 INVALID_PARAM 物理上都是"业务错"，
      但前者需要换资源、后者需要改参数，因此必须分类
    """
    BUSINESS_RULE_VIOLATION = "business_rule_violation"
    """业务硬规则拒绝（如违约超限、积分不足）。无法绕过，需告知用户"""

    RESOURCE_CONFLICT = "resource_conflict"
    """资源冲突（如座位被占）。可引导用户改换资源后重试"""

    INVALID_PARAMS = "invalid_params"
    """参数错误（如时长越界、不存在的ID）。Agent修正参数即可"""

    TRANSIENT_FAILURE = "transient_failure"
    """瞬态故障（DB连接抖动、网络超时）。自动重试通常可恢复"""

    UNRECOVERABLE = "unrecoverable"
    """不可恢复（权限拒绝、未知系统错误）。直接终止"""


class BookingDomainError(Exception):
    """
    预定业务的基类异常。

    ⭐ 每个具体异常必须声明自己的 ErrorCategory，
       这是驱动 Self-Healing 策略决策的元数据。
    """
    category: ErrorCategory = ErrorCategory.UNRECOVERABLE  # 子类必须覆盖

    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(f"[{error_code}] {message}")


class SeatOccupiedError(BookingDomainError):
    category = ErrorCategory.RESOURCE_CONFLICT

    def __init__(self, message="座位已被占用或不存在"):
        super().__init__("SEAT_OCCUPIED", message)


class ViolationLimitError(BookingDomainError):
    category = ErrorCategory.BUSINESS_RULE_VIOLATION

    def __init__(self, message="违约次数超限"):
        super().__init__("VIOLATION_LIMIT", message)


class InvalidParamError(BookingDomainError):
    category = ErrorCategory.INVALID_PARAMS

    def __init__(self, message="参数不合法"):
        super().__init__("INVALID_PARAM", message)


class SystemBusyError(BookingDomainError):
    category = ErrorCategory.TRANSIENT_FAILURE

    def __init__(self, message="底层数据库或系统异常"):
        super().__init__("DB_SYSTEM_ERROR", message)


class UserNotFoundError(BookingDomainError):
    category = ErrorCategory.UNRECOVERABLE

    def __init__(self, message="查无此人"):
        super().__init__("USER_NOT_FOUND", message)


class SeatNotFoundError(BookingDomainError):
    category = ErrorCategory.RESOURCE_CONFLICT

    def __init__(self, message="座位号不存在"):
        super().__init__("SEAT_NOT_FOUND", message)


# ==========================================
# ⭐ CRUD 扩展：订单管理相关异常 (Read/Update/Delete)
# ==========================================
class BookingNotFoundError(BookingDomainError):
    """订单号不存在（用户传错了 booking_id）"""
    category = ErrorCategory.INVALID_PARAMS

    def __init__(self, message="订单号不存在"):
        super().__init__("BOOKING_NOT_FOUND", message)


class NotYourBookingError(BookingDomainError):
    """
    越权操作：订单存在但不属于当前认证用户。

    ⭐ 安全考虑：category 选 UNRECOVERABLE 而非 BUSINESS_RULE_VIOLATION。
    业务规则违反会向用户解释具体原因（"你不能取消别人的订单"），
    这会暴露"该订单存在"的信息。安全场景下应该静默拒绝，
    不给攻击者任何关于资源存在性的探测信号。
    """
    category = ErrorCategory.UNRECOVERABLE

    def __init__(self, message="操作无法完成"):
        super().__init__("NOT_YOUR_BOOKING", message)


class BookingAlreadyCancelledError(BookingDomainError):
    """订单已经是 CANCELLED 状态，不能重复取消"""
    category = ErrorCategory.BUSINESS_RULE_VIOLATION

    def __init__(self, message="该订单已被取消，无法重复操作"):
        super().__init__("BOOKING_ALREADY_CANCELLED", message)