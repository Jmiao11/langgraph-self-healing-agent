# utils/healing_trace.py
"""
自愈轨迹摘要器（纯函数）。

把 AgentState.trace（本轮决策链路的原始结构化记录）翻译成前端可直接渲染的
“自愈轨迹”展示步骤。trace 由各子图节点写入、merge_trace 每轮清零，因此
传入的就是“本轮”的完整链路，无需再切分。

⭐ 设计动机：
自愈是项目核心卖点，但过程藏在后端日志和异常链里、UI 上看不见——一个“看不见的
核心功能”在面试里几乎等于不存在。把 trace 提炼成 first-class 的展示数据，让
“代码层确定性自愈 / V4 0-LLM 短路 / 熔断器”在前端肉眼可见。

⭐ 为什么放 utils（仅依赖 stdlib）而非子图模块：
- 不引入 langgraph / mcp 重依赖 → 可零副作用 L1 单测
- “是否自愈 / 短路省了几次 LLM / 是否熔断”是这套叙事的核心，值得被测试钉死
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


def summarize_self_healing_trace(trace: list[dict] | None) -> dict:
    """把本轮 trace 提炼成自愈轨迹摘要。

    Args:
        trace: AgentState.trace（本轮的原始决策链路记录列表）

    Returns:
        {
          "healing_triggered": bool,    # 本轮是否发生了自愈
          "shortcut_count": int,        # V4 0-LLM 短路命中次数
          "llm_classify_calls": int,    # 降级用 LLM 分类的次数
          "circuit_broken": bool,       # 是否触发熔断
          "steps": [ {"icon","title","detail"} ... ],  # 有序展示步骤
        }
    """
    trace = trace or []
    steps: list[dict] = []
    healing_triggered = False
    shortcut_count = 0
    llm_classify_calls = 0
    circuit_broken = False

    for entry in trace:
        if not isinstance(entry, dict):
            continue
        node = entry.get("node")

        # 工具执行出错 → 自愈链路的起点
        if node == "tools" and entry.get("status") == "error":
            healing_triggered = True
            steps.append({
                "icon": "🔧",
                "title": f"检测到工具错误：{entry.get('tool_name', '未知工具')}",
                "detail": "",
            })

        elif node == "error_analyzer":
            decision = entry.get("decision")

            if decision == "shortcut_via_metadata":
                # ⭐ V4 核心：已知异常，命中策略表，0 次 LLM 调用
                healing_triggered = True
                shortcut_count += 1
                steps.append({
                    "icon": "⚡",
                    "title": f"错误分类：{_category_cn(entry.get('category'))}"
                             f"（命中策略表，0 次 LLM 调用）",
                    "detail": entry.get("user_summary", "") or "",
                })

            elif decision == "classified_by_llm":
                # 未知异常，降级用 LLM 做语义分类
                healing_triggered = True
                llm_classify_calls += 1
                steps.append({
                    "icon": "🧠",
                    "title": f"错误分类：{_category_cn(entry.get('category'))}"
                             f"（未知异常，LLM 降级分类）",
                    "detail": entry.get("reasoning", "") or entry.get("user_summary", "") or "",
                })

            elif decision == "circuit_breaker_triggered":
                # 熔断：重试达上限，强制停止
                healing_triggered = True
                circuit_broken = True
                steps.append({
                    "icon": "🔥",
                    "title": "熔断触发：重试已达上限，停止自愈",
                    "detail": "防止级联故障，转为向用户坦白并建议稍后重试。",
                })
        # booking_agent / 其他节点不计入自愈面板，保持聚焦

    return {
        "healing_triggered": healing_triggered,
        "shortcut_count": shortcut_count,
        "llm_classify_calls": llm_classify_calls,
        "circuit_broken": circuit_broken,
        "steps": steps,
    }