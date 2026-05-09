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