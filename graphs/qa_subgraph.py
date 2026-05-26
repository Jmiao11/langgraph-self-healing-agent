# graphs/qa_subgraph.py
import dotenv
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

# ⭐ 导入我们刚写好的核心服务
from utils.security_policy import build_identity_guard

from utils.message_filters import build_subgraph_message_view
# ⭐ QA 子图自己的工具集
QA_OWN_TOOLS = {"search_library_rules"}

dotenv.load_dotenv()

# ✅ 换成全局引入
from schemas.state import AgentState


def build_qa_agentic_graph(retrieval_service, llm):
    """
    Args:
        retrieval_service: RAG 检索服务
        llm: 从 llm_pool 注入，应该是 reasoning 类
    """

    # 2. 增强工具定义：让 LLM 知道它可以传 category
    @tool
    def search_library_rules(query: str, category: str = None) -> str:
        """
        当用户询问规章制度、预约规则时调用此工具。
        参数:
        - query: 用户问题的核心搜索词。
        - category: (可选) 如果你判断问题明确属于某个特定领域，请传入以下选项之一以提升精确度：
          ['预约规则', '违约处罚', '开放时间', '行为规范', '其他']
        """
        return retrieval_service.search_rules(query, category)

    tools = [search_library_rules]
    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: AgentState):
        student_id = state.get("student_id") or "未知用户"
        sys_msg = SystemMessage(content=build_identity_guard(student_id=student_id))

        # ⭐ 同样应用本地视图过滤
        local_view = build_subgraph_message_view(
            state["messages"],
            own_tool_names=QA_OWN_TOOLS,
        )
        msgs = [sys_msg] + local_view

        response = llm_with_tools.invoke(msgs)

        has_tool_calls = bool(getattr(response, "tool_calls", None))
        trace_entry = {
            "node": "qa_agent",
            "decision": "call_search" if has_tool_calls else "direct_answer"
        }

        return {"messages": [response], "trace": [trace_entry]}

    # 构建工作流...
    qa_sub = StateGraph(AgentState)
    qa_sub.add_node("agent", agent_node)
    qa_sub.add_node("tools", ToolNode(tools))

    qa_sub.add_edge(START, "agent")
    qa_sub.add_conditional_edges("agent", tools_condition)
    qa_sub.add_edge("tools", "agent")

    return qa_sub.compile()

