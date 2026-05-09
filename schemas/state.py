import operator
from typing import Annotated, TypedDict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

def add_list(left: list | None, right: list | None) -> list:
    """通用追加 reducer"""
    left = left or []
    right = right or []
    return left + right


def merge_trace(left: list | None, right: list | None) -> list:
    """
    Trace 字段专用 reducer，支持轮次级重置。

    约定：如果 right 中包含哨兵字典 {"_reset": True}，则丢弃 left，
    用 right 中除哨兵外的部分作为新值。

    这让节点可以通过返回 [{"_reset": True}, {...实际记录...}]
    实现"清零 trace 并写入新记录"的语义，而不破坏 LangGraph
    "节点只返回 patch"的约束。
    """
    left = left or []
    right = right or []

    has_reset = any(isinstance(r, dict) and r.get("_reset") for r in right)
    if has_reset:
        return [r for r in right if not (isinstance(r, dict) and r.get("_reset"))]

    return left + right

class AgentState(TypedDict):
    """
    全局唯一的状态总线 (State Bus)
    所有 Subgraph 必须严格遵守此数据结构，不允许私自扩展不可见的字段。
    """
    # ==========================================
    # 1. 核心对话流 (LangGraph 原生要求)
    # ==========================================
    messages: Annotated[list[BaseMessage], add_messages]

    # ==========================================
    # 2. 路由控制层 (Router Outputs)
    # ==========================================
    intent: str | None
    security_decision: str | None

    # ==========================================
    # 3. 用户态上下文 (User Profile)
    # ==========================================
    student_id: str | None
    user_name: str | None
    # ⭐ 当前轮次用户的真实意图（每轮 router 阶段固化）
    # 不能用 messages[0]，因为持久化会话中 messages[0] 是历史首句，
    # 不是当前轮次的意图。
    current_user_intent: str | None
    # ==========================================
    # 4. 动态业务态 (Business Context)
    # ==========================================
    context: dict[str, Any] | None

    # ==========================================
    # 5. 错误与自愈系统 (Self-Healing Context)
    # ==========================================
    error: dict[str, Any] | None
    # ⭐ 新增：自愈尝试次数计数器（防止无限重试导致死循环）
    repair_attempts: int | None

    # ==========================================
    # 6. 系统可观测性 (Observability)
    # ==========================================
    # 当前轮次的决策链路追踪。每轮入口（rule_filter）会清零。
    # 历史链路追踪应走外部观测系统（LangSmith / 日志平台），不在 state 中保留。
    trace: Annotated[list[dict], merge_trace]  # ⭐ 从 add_list 改为 merge_trace