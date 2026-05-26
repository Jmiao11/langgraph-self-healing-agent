#graphs/booking_self_healing_subgraph.py
import sys
import json
import os
from typing import Literal

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from schemas.exceptions import BookingDomainError
# ⭐ 引入刚刚统一的全局 State
from schemas.state import AgentState
from services.booking_service import BookingService
from utils.security_policy import build_identity_guard

from utils.message_filters import build_subgraph_message_view
BOOKING_OWN_TOOLS = {"book_seat_tool", "search_free_seats_tool", "get_my_info_tool"}

import dotenv

dotenv.load_dotenv()

MAX_REPAIR_ATTEMPTS = 2  # 同一次对话允许的最大自愈次数

# ==========================================
# ⭐ 错误分类 -> 处理策略 映射表（确定性决策）
# ==========================================
# 每个 category 对应一条策略指令模板，由代码层确定性地选择，
# 而非由 LLM 自由发挥。这是 Classify-then-Decide 架构的核心。
REPAIR_STRATEGY_MAP = {
    "business_rule_violation": {
        "should_retry": False,
        "instruction_template": (
            "【系统诊断】：业务规则拒绝（{user_summary}）。"
            "【强指令】：禁止再调用任何工具尝试。请直接用自然语言向用户解释情况，"
            "并建议他们采取线下流程（如申诉、缴费、等待规则刷新）。"
        )
    },
    "resource_conflict": {
        "should_retry": True,
        "instruction_template": (
            "【系统诊断】：资源冲突（{user_summary}）。"
            "【强指令】：当前资源不可用。请先调用 search_free_seats_tool 查询可用资源，"
            "向用户展示替代选项后，等待用户明确选择新资源再尝试预定。"
        )
    },
    "invalid_params": {
        "should_retry": True,
        "instruction_template": (
            "【系统诊断】：参数不合法（{user_summary}）。"
            "【强指令】：请仔细审视上次工具调用的参数，找出违反约束的字段（如时长越界、"
            "座位号不存在），修正后重新调用工具。如无法判断如何修正，向用户提问澄清。"
        )
    },
    "transient_failure": {
        "should_retry": True,
        "instruction_template": (
            "【系统诊断】：瞬态故障（{user_summary}）。"
            "【强指令】：底层服务出现暂时性异常。请用完全相同的参数重新调用一次工具。"
            "如再次失败，请告知用户系统繁忙，建议稍后重试。"
        )
    },
    "unrecoverable": {
        "should_retry": False,
        "instruction_template": (
            "【系统诊断】：不可恢复错误（{user_summary}）。"
            "【强指令】：禁止再调用任何工具。直接向用户坦诚说明操作无法完成，"
            "并建议联系人工服务台。"
        )
    },
}

# ==========================================
# 1. LLM 输出结构（仅做错误分类，不做决策）
# ==========================================
class ErrorClassification(BaseModel):
    """
    Self-Healing 的第一阶段：LLM 仅输出错误的语义分类。

    ⭐ 关键设计：剥离"决策权"——LLM 只回答 What（这是什么错），
       不回答 How（该怎么处理）。处理策略由代码层根据分类查表决定。
    """
    reasoning: str = Field(
        description="基于错误报文的 message 和 error_code 字面意思，分析这次失败的本质语义。"
    )
    category: Literal[
        "business_rule_violation",
        "resource_conflict",
        "invalid_params",
        "transient_failure",
        "unrecoverable"
    ] = Field(
        description=(
            "错误的语义分类（必须严格选择以下之一）：\n"
            "- business_rule_violation: 业务硬规则拒绝，如违约超限、积分不足、账户冻结。"
            "  特征：错误是『系统拒绝服务』，不是『参数错』也不是『资源被占』。\n"
            "- resource_conflict: 资源冲突，如座位已被占、订单已锁定。"
            "  特征：错误是『资源不可用』，换个资源可能就行。\n"
            "- invalid_params: 参数错误，如时长越界、ID 不存在、格式错误。"
            "  特征：错误源于调用方传参不当，修正参数即可恢复。\n"
            "- transient_failure: 瞬态故障，如 DB 连接超时、网络抖动、底层服务暂时不可用。"
            "  特征：错误与业务无关，重试通常能成功。\n"
            "- unrecoverable: 不可恢复，如权限拒绝、未知系统错、用户不存在。"
            "  特征：错误本身决定了无法在当前会话中修复。"
        )
    )
    user_facing_summary: str = Field(
        description="用一两句通俗的话向终端用户解释发生了什么（不要暴露 error_code 等技术细节）。"
    )

async def build_booking_app(llm):
    print("⏳ [Booking Graph] 正在连接本地 MCP 服务，组装纯净工具箱...")

    mcp_config = {
        "dream-room-mcp": {
            "command": sys.executable,
            "args": ["mcp_server/server.py"],
            "transport": "stdio"
        }
    }

    client = MultiServerMCPClient(mcp_config)
    raw_mcp_tools = await client.get_tools()

    # 1. 实例化净化后的 Service 层
    booking_service = BookingService(raw_mcp_tools)

    # 2. ⭐ 工具工厂：根据已认证身份动态生成工具集
    # 关键设计：student_id 从闭包捕获，LLM 完全无法看到此参数
    def make_tools_for_user(authenticated_sid: str):
        @tool
        async def book_seat_tool(seat_id: int, duration: int) -> str:
            """执行座位预定。系统已自动绑定您的身份，您只需提供座位号和时长。
            参数:
            - seat_id: 座位编号
            - duration: 预定时长（小时，1-8）
            """
            try:
                # ⭐ 强制使用经过认证的 student_id，无视任何外部输入
                data = await booking_service.book(authenticated_sid, seat_id, duration)
                return f"✅ 预定成功！订单号: {data.get('booking_id')}"
            except BookingDomainError as e:
                return f"[TOOL_ERROR] error_code={e.error_code}, message={e.message}"

        @tool
        async def search_free_seats_tool(zone_type: str = None) -> str:
            """查询目前空闲的座位。如果用户没有指定特定区域，请不要传递此参数。"""
            return await booking_service.search(zone_type)

        @tool
        async def get_my_info_tool() -> str:
            """查询当前登录用户的积分和违约信息。系统已自动绑定您的身份。"""
            return await booking_service.get_user_info(authenticated_sid)

        return [book_seat_tool, search_free_seats_tool, get_my_info_tool]

    # ==========================================
    # 2. 定义 Graph Nodes (图节点)
    # ==========================================

    async def booking_agent_node(state: AgentState):
        """主控大脑：负责与用户对话、决定调用什么工具"""
        student_id = state.get("student_id")
        if not student_id:
            from langchain_core.messages import AIMessage
            return {
                "messages": [AIMessage(content="⚠️ 系统未检测到您的认证身份，无法执行预定操作。请重新登录。")]
            }

        user_tools = make_tools_for_user(student_id)
        llm_with_tools = llm.bind_tools(user_tools)

        sys_msg = SystemMessage(content=build_identity_guard(student_id=student_id))

        # ⭐ 关键改动：从全局 messages 中过滤本子图的本地视图
        # 避免看到其他子图（如 qa）的工具调用记录污染上下文
        local_view = build_subgraph_message_view(
            state["messages"],
            own_tool_names=BOOKING_OWN_TOOLS,
        )
        messages = [sys_msg] + local_view

        response = await llm_with_tools.ainvoke(messages)

        has_tool_calls = bool(getattr(response, "tool_calls", None))
        trace_entry = {
            "node": "booking_agent",
            "decision": "call_tools" if has_tool_calls else "respond_to_user",
            "tools_called": [tc.get("name") for tc in (response.tool_calls or [])] if has_tool_calls else []
        }

        return {"messages": [response], "trace": [trace_entry]}

    def error_analyzer_node(state: AgentState):
        """
        Self-Healing 核心节点：Classify-then-Decide 双阶段架构。

        阶段1: 调用 LLM 输出错误的语义分类（仅 What，不含 How）
        阶段2: 代码层根据分类查 REPAIR_STRATEGY_MAP，确定性地生成处理指令

        ⭐ 加固：引入熔断机制，防止无限重试。
        """
        current_attempts = state.get("repair_attempts") or 0
        print(f"🚨 [Self-Healing] 触发动态异常诊断... (第 {current_attempts + 1}/{MAX_REPAIR_ATTEMPTS} 次尝试)")

        last_tool_msg = state["messages"][-1].content

        # ==========================================
        # 0. 熔断检查：超限直接终止
        # ==========================================
        if current_attempts >= MAX_REPAIR_ATTEMPTS:
            print(f"🛑 [Circuit Breaker] 自愈次数已达上限 ({MAX_REPAIR_ATTEMPTS})，强制终止重试链路")
            abort_msg = SystemMessage(
                content=(
                    f"【系统熔断指令】：自愈系统已尝试修复 {current_attempts} 次仍未成功。"
                    f"最后一次错误：{last_tool_msg}。"
                    f"请立刻停止任何工具调用，用自然语言向用户坦诚说明操作无法完成，"
                    f"建议用户稍后重试或联系人工服务台。绝对禁止再次调用任何工具。"
                )
            )
            return {
                "messages": [abort_msg],
                "error": {"action": "circuit_break", "detail": last_tool_msg, "attempts": current_attempts},
                "trace": [{"node": "error_analyzer", "decision": "circuit_break", "attempts": current_attempts}]
            }

        # ==========================================
        # 1. 阶段1：LLM 错误分类（仅做语义理解）
        # ==========================================
        # ⭐ 优先使用 router 阶段固化的当前轮次意图
        # 兜底：如果上游因某种原因没设置（如直接绕过 router 调用本子图），
        # 才退回到 messages[0]，并打印警告
        user_intent = state.get("current_user_intent")
        if not user_intent:
            print("⚠️ [Error Analyzer] current_user_intent 未设置，回退到 messages[0]")
            user_intent = state["messages"][0].content if state["messages"] else "未知"

        classifier_llm = llm.with_structured_output(ErrorClassification)

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "你是自习室系统的『错误分类器』(Error Classifier)。\n"
             "你的唯一职责是：阅读底层工具抛出的错误报文，判断它属于 5 类错误中的哪一类。\n\n"
             "⚠️ 你不需要决定『怎么处理这个错误』——处理策略由系统代码层根据你的分类自动决定。\n"
             "你只需要做好『语义分类』这一件事。\n\n"
             "【关键边界澄清 - 必读】\n"
             "business_rule_violation 与 resource_conflict 容易混淆，必须区分：\n"
             "- **business_rule_violation**：拒绝是针对【用户身份/账户状态】的。\n"
             "  例如：违约超限、积分不足、账户冻结、未实名。\n"
             "  特征：换一个『资源』也救不了，因为问题出在『用户身上』。\n"
             "- **resource_conflict**：拒绝是针对【所请求的资源】的。\n"
             "  例如：座位已被占（SEAT_OCCUPIED）、订单已锁定、库存售罄、文档被他人编辑中。\n"
             "  特征：换一个『资源』就能成功，问题不在用户身上。\n\n"
             "【判断口诀】：问自己一句『换个对象重试有用吗？』\n"
             "- 有用 → resource_conflict\n"
             "- 没用（限制锁在用户身上） → business_rule_violation\n\n"
             "【其他三类】\n"
             "- invalid_params：参数本身不合法（时长越界、ID格式错），修参数就行。\n"
             "- transient_failure：底层抖动（DB连接超时、网络波动），重试可恢复。\n"
             "- unrecoverable：用户不存在、权限拒绝、未知错误。\n\n"
             "【自检要点】\n"
             "- 仔细读 error_code 字面含义。SEAT_OCCUPIED 这类带具体资源名的错误码，\n"
             "  几乎必然是 resource_conflict 而非 business_rule。\n"
             "- VIOLATION_LIMIT、INSUFFICIENT_POINTS 这类带用户状态名的错误码，\n"
             "  才是 business_rule。\n"
             "- 拿不准时，优先选 unrecoverable（保守策略，宁可误终止不可误重试）。"),
            ("human", "用户的原始诉求: {user_intent}\n\n底层抛出的错误报文: {last_tool_msg}")
        ])

        chain = prompt | classifier_llm
        classification = chain.invoke({
            "user_intent": user_intent,
            "last_tool_msg": last_tool_msg
        })

        print(f"🧠 [LLM 分类]: {classification.category}")
        print(f"   ↳ 推理: {classification.reasoning}")
        print(f"   ↳ 用户摘要: {classification.user_facing_summary}")

        # ==========================================
        # 2. 阶段2：代码层确定性决策（查策略表）
        # ==========================================
        strategy = REPAIR_STRATEGY_MAP.get(classification.category)
        if not strategy:
            # 防御性兜底：LLM 返回了未知分类（理论上 Literal 已约束，但稳妥起见兜一层）
            print(f"⚠️ [Strategy] 未知分类 {classification.category}，按 unrecoverable 处理")
            strategy = REPAIR_STRATEGY_MAP["unrecoverable"]

        instruction = strategy["instruction_template"].format(
            user_summary=classification.user_facing_summary
        )

        print(f"🛠️ [代码决策]: should_retry={strategy['should_retry']}")

        repair_msg = SystemMessage(content=instruction)

        return {
            "messages": [repair_msg],
            "error": {
                "category": classification.category,
                "should_retry": strategy["should_retry"],
                "detail": last_tool_msg,
            },
            "repair_attempts": current_attempts + 1,
            "trace": [{
                "node": "error_analyzer",
                "category": classification.category,
                "should_retry": strategy["should_retry"],
                "attempts": current_attempts + 1
            }]
        }


    # ==========================================
    # 3. 定义 Routing Edges (路由条件)
    # ==========================================

    def should_continue(state: AgentState):
        """决定 Agent 思考完后，是去调工具，还是返回给用户"""
        last_msg = state["messages"][-1]
        if last_msg.tool_calls:
            return "tools"
        return END

    # ==========================================
    # 极致精简的异常嗅探器 (不用再解包 JSON 了！)
    # ==========================================
    def check_tool_error(state: AgentState):
        """嗅探器：通过特征字符串拦截异常"""
        last_msg = state["messages"][-1]

        # 只拦截 book_seat_tool 的输出
        if getattr(last_msg, "name", "") != "book_seat_tool":
            return "booking_agent"

        content_str = str(last_msg.content)

        # 极其优雅的判定：只要 Tool 返回了带有特定前缀的字符串，立刻路由去自愈！
        if "[TOOL_ERROR]" in content_str:
            print(f"⚠️ [Graph 嗅探] 捕获到业务拦截信号，转向 Error Analyzer...")
            return "error_analyzer"

        return "booking_agent"

    # ==========================================
    # 4. 编排并编译 StateGraph
    # ==========================================

    # ⭐ 注意：ToolNode 需要工具列表，但工具是动态生成的
    # 解决方案：构造一个"代理 ToolNode"，它在运行时才解析工具
    async def dynamic_tool_node(state: AgentState):
        """动态工具节点：根据当前用户身份执行工具调用"""
        student_id = state.get("student_id")
        if not student_id:
            from langchain_core.messages import ToolMessage
            last_msg = state["messages"][-1]
            tool_call_id = last_msg.tool_calls[0]["id"] if last_msg.tool_calls else "unknown"
            return {
                "messages": [ToolMessage(
                    content="[TOOL_ERROR] error_code=NO_AUTH, message=未认证用户禁止调用工具",
                    tool_call_id=tool_call_id
                )],
                "trace": [{"node": "tools", "decision": "no_auth_abort"}]
            }

        user_tools = make_tools_for_user(student_id)
        tool_node = ToolNode(user_tools)
        result = await tool_node.ainvoke(state)

        # ⭐ 记录工具执行结果（成功/失败）
        tool_messages = result.get("messages", [])
        trace_entries = []
        for tm in tool_messages:
            content_str = str(tm.content)
            is_error = "[TOOL_ERROR]" in content_str
            trace_entries.append({
                "node": "tools",
                "tool_name": getattr(tm, "name", "unknown"),
                "status": "error" if is_error else "success"
            })

        return {**result, "trace": trace_entries}


    workflow = StateGraph(AgentState)

    # 注册三大核心组件
    workflow.add_node("booking_agent", booking_agent_node)
    workflow.add_node("tools", dynamic_tool_node)  # ⭐ 改为动态节点
    workflow.add_node("error_analyzer", error_analyzer_node)  # ⭐ 纯正的自愈节点

    # 编排数据流 (Flow)
    workflow.add_edge(START, "booking_agent")

    # Agent 决定是否调工具
    workflow.add_conditional_edges("booking_agent", should_continue, {
        "tools": "tools",
        END: END
    })

    # 工具执行完毕后，走错误嗅探逻辑
    workflow.add_conditional_edges("tools", check_tool_error, {
        "error_analyzer": "error_analyzer",  # 抓到错 -> 去看病
            "booking_agent": "booking_agent"  # 没抓到 -> 回去继续思考
    })

    # 诊断完开出处方后，强制回传给 Agent 执行修复动作
    workflow.add_edge("error_analyzer", "booking_agent")

    return workflow.compile()