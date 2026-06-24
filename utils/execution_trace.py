# utils/execution_trace.py
"""
执行轨迹摘要器（纯函数）。

把 AgentState.trace（本轮决策链路的原始结构化记录）翻译成前端可直接渲染的
“执行轨迹”展示步骤。trace 由各子图节点写入、merge_trace 每轮清零，因此
传入的就是“本轮”的完整链路，无需再切分。

⭐ 设计动机：
Agent 的工具调用与异常自愈都发生在后端，UI 上看不见——“工具是否真被调用、
调了哪个、成败如何、失败后又怎么自愈”全是黑箱。把 trace 提炼成 first-class 的
展示数据，让整条执行链路（工具调用 + V4 0-LLM 短路 + 熔断）在前端肉眼可见。

本模块是 healing_trace.summarize_self_healing_trace 的超集演进：
从“只展示自愈”扩展为“展示完整执行轨迹”（工具调用 + 自愈）。

⭐ 为什么放 utils（仅依赖 stdlib）而非子图模块：
- 不引入 langgraph / mcp 重依赖 → 可零副作用 L1 单测
- “调了几次工具 / 是否自愈 / 短路省了几次 LLM / 是否熔断”是这套可观测性叙事的
  核心，值得被测试钉死
- 摘要器是响应契约的一部分，理应像 build_history_view_or_none 一样可独立验证
"""

# 错误分类 → 中文展示名（与 REPAIR_STRATEGY_MAP 的 5 类一一对应）
_CATEGORY_CN = {
    "business_rule_violation": "业务规则拒绝",
    "resource_conflict": "资源冲突",
    "invalid_params": "参数不合法",
    "transient_failure": "瞬态故障",
    "unrecoverable": "不可恢复错误",
}


def _category_cn(category) -> str:
    """分类码 → 中文名；未知码原样回显（防御未来新增分类）。"""
    return _CATEGORY_CN.get(category, category if category else "未知")


def summarize_execution_trace(trace: list[dict] | None) -> dict:
    """把本轮 trace 提炼成执行轨迹摘要。

    Args:
        trace: AgentState.trace（本轮的原始决策链路记录列表）

    Returns:
        {
          "has_activity": bool,         # 本轮是否有工具调用或自愈（决定是否显示面板）
          "tool_call_count": int,       # 工具调用次数（含自愈后的二次调用）
          "healing_triggered": bool,    # 是否发生了自愈
          "shortcut_count": int,        # V4 0-LLM 短路命中次数
          "llm_classify_calls": int,    # 降级用 LLM 分类的次数
          "circuit_broken": bool,       # 是否触发熔断
          "steps": [ {"icon","title","detail"} ... ],  # 有序展示步骤
        }
    """
    trace = trace or []
    steps: list[dict] = []
    tool_call_count = 0
    healing_triggered = False
    shortcut_count = 0
    llm_classify_calls = 0
    circuit_broken = False

    for entry in trace:
        if not isinstance(entry, dict):
            continue
        node = entry.get("node")

        # ---- 工具调用（成败一体）----
        if node == "tools":
            status = entry.get("status")
            if status in ("success", "error"):
                tool_call_count += 1
                tool_name = entry.get("tool_name", "未知工具")
                if status == "success":
                    steps.append({
                        "icon": "▸",
                        "title": f"调用工具：{tool_name} · ✓ 成功",
                        "detail": "",
                    })
                else:
                    steps.append({
                        "icon": "▸",
                        "title": f"调用工具：{tool_name} · ✕ 失败",
                        "detail": "",
                    })
            # 无 status 的 tools 记录（如 no_auth_abort）不计入展示

        # ---- 自愈分析 ----
        elif node == "error_analyzer":
            decision = entry.get("decision")

            if decision == "shortcut_via_metadata":
                # ⭐ V4 核心：已知异常，命中策略表，0 次 LLM 调用
                healing_triggered = True
                shortcut_count += 1
                steps.append({
                    "icon": "◆",
                    "title": f"错误分类：{_category_cn(entry.get('category'))}"
                             f"（命中策略表，0 次 LLM 调用）",
                    "detail": entry.get("user_summary", "") or "",
                })

            elif decision == "classified_by_llm":
                # 未知异常，降级用 LLM 做语义分类
                healing_triggered = True
                llm_classify_calls += 1
                steps.append({
                    "icon": "◇",
                    "title": f"错误分类：{_category_cn(entry.get('category'))}"
                             f"（未知异常，LLM 降级分类）",
                    "detail": entry.get("reasoning", "") or entry.get("user_summary", "") or "",
                })

            elif decision == "circuit_breaker_triggered":
                # 熔断：重试达上限，强制停止
                healing_triggered = True
                circuit_broken = True
                steps.append({
                    "icon": "⊘",
                    "title": "熔断触发：重试已达上限，停止自愈",
                    "detail": "防止级联故障，转为向用户坦白并建议稍后重试。",
                })
        # booking_agent / 其他节点不计入面板（call_tools 的工具名已由 tools 记录覆盖）

    has_activity = tool_call_count > 0 or healing_triggered

    return {
        "has_activity": has_activity,
        "tool_call_count": tool_call_count,
        "healing_triggered": healing_triggered,
        "shortcut_count": shortcut_count,
        "llm_classify_calls": llm_classify_calls,
        "circuit_broken": circuit_broken,
        "steps": steps,
    }