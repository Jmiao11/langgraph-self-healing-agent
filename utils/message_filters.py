# utils/message_filters.py
"""
子图本地消息视图过滤器。

设计动机：
LangGraph 的 state.messages 是全局共享的——所有子图的工具调用记录
都会写回同一个 list。当用户从 booking 子图切换到 qa 子图时，
qa 子图的 LLM 会看到上一轮 booking 子图的 ToolMessage（如"积分100, 违约0"），
导致跨意图的上下文污染——LLM 会在不相关的回答里复读历史工具结果。

解决思路（两阶段过滤）：
- 阶段1（V2）：过滤"其他子图的工具调用链"——
  AIMessage(含 tool_calls) → 看 tool name 归属
  ToolMessage → 看 tool_call_id 归属
  AIMessage(纯文本) → 看上一条是否为"其他子图的 ToolMessage"，是则视为"对工具结果的复述"过滤
- 阶段2（V3）：过滤"被孤立的历史 HumanMessage"——
  阶段1 之后，可能出现"用户问过但所有回答都被洗掉"的 HumanMessage。
  LLM 看到这种孤立提问，会自作主张补一句"那个问题建议你去 XX 查"——
  破坏当前回答的纯粹性。故需要"配对过滤"。

架构涵义：
明确区分两个概念——
- "state 全集"：系统记账（用于持久化、trace、摘要、可观测性）
- "LLM 上下文"：agent 视野（用于本轮推理，不应见到其他子图的工具细节）

边界处理：
- 末尾 HumanMessage：永远保留（这是触发本轮的输入）
- 连续多条 HumanMessage：第一条的"回答集"为空，视为"用户未获回答"而非"回答被过滤"，保留
- 仅当"回答集非空 ∧ 所有回答都被阶段1过滤"时，才判定为"孤立 HumanMessage"
"""
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
)


def _filter_foreign_tool_chains(
    messages: list[BaseMessage],
    own_tool_names: set[str],
) -> list[BaseMessage]:
    """阶段1：过滤其他子图的工具调用链 + 对其结果的复述性 AIMessage。"""
    own_tool_call_ids: set[str] = set()
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                if tc.get("name") in own_tool_names:
                    own_tool_call_ids.add(tc.get("id"))

    filtered: list[BaseMessage] = []
    last_was_foreign_tool_msg = False

    for m in messages:
        if isinstance(m, (SystemMessage, HumanMessage)):
            filtered.append(m)
            last_was_foreign_tool_msg = False
            continue

        if isinstance(m, ToolMessage):
            if m.tool_call_id in own_tool_call_ids:
                filtered.append(m)
                last_was_foreign_tool_msg = False
            else:
                last_was_foreign_tool_msg = True
            continue

        if isinstance(m, AIMessage):
            has_tool_calls = bool(getattr(m, "tool_calls", None))
            if has_tool_calls:
                tc_names = {tc.get("name") for tc in m.tool_calls}
                if tc_names.issubset(own_tool_names):
                    filtered.append(m)
                last_was_foreign_tool_msg = False
                continue
            # 纯文本 AIMessage
            if last_was_foreign_tool_msg:
                pass  # 工具结果的复述 → 过滤
            else:
                filtered.append(m)
            last_was_foreign_tool_msg = False
            continue

        # 兜底：未知消息类型保守保留
        filtered.append(m)
        last_was_foreign_tool_msg = False

    return filtered


def _drop_orphan_human_messages(
    original: list[BaseMessage],
    filtered: list[BaseMessage],
) -> list[BaseMessage]:
    """
    阶段2：丢弃孤立的历史 HumanMessage。

    判定规则：对原始 messages 中的每一条 HumanMessage 计算"回答集"——
    从它的下一条开始，到下一条 HumanMessage 或末尾为止，区间内的所有 AIMessage。
    - 末尾 HumanMessage（无后续消息可言）→ 保留（这是本轮输入）
    - 回答集为空（用户连续提问没等到回答）→ 保留
    - 回答集非空但所有 AIMessage 都不在 filtered 里 → 视为孤立，丢弃
    - 回答集中至少一条 AIMessage 保留 → 留下 HumanMessage
    """
    # 找出原始消息中"被过滤光回答"的 HumanMessage 索引
    filtered_ids = {id(m) for m in filtered}
    orphan_human_ids: set[int] = set()

    n = len(original)
    for i, m in enumerate(original):
        if not isinstance(m, HumanMessage):
            continue

        # 收集回答集（i+1 到下一个 HumanMessage 或末尾）
        answer_set: list[AIMessage] = []
        for j in range(i + 1, n):
            nxt = original[j]
            if isinstance(nxt, HumanMessage):
                break
            if isinstance(nxt, AIMessage):
                answer_set.append(nxt)

        # 末尾 HumanMessage（i 是最后一条 user 提问，后面只有少量或无 AI）
        # 用 "i 之后是否还有 HumanMessage" 来判断更准确
        is_last_human = not any(
            isinstance(original[j], HumanMessage) for j in range(i + 1, n)
        )
        if is_last_human:
            continue  # 永远保留

        # 回答集为空（连续提问的早一条）→ 保留
        if not answer_set:
            continue

        # 检查回答集中是否至少有一条 AIMessage 在 filtered 里
        any_answer_survived = any(id(a) in filtered_ids for a in answer_set)
        if not any_answer_survived:
            orphan_human_ids.add(id(m))

    # 从 filtered 中剔除孤立 HumanMessage
    return [m for m in filtered if id(m) not in orphan_human_ids]


def build_subgraph_message_view(
    messages: list[BaseMessage],
    own_tool_names: set[str],
) -> list[BaseMessage]:
    """
    为子图构造"本地消息视图"。两阶段过滤：
    1. 过滤其他子图的工具调用链 + 复述
    2. 过滤被孤立的历史 HumanMessage（无配对回答的）

    Args:
        messages: state 全集中的 messages
        own_tool_names: 当前子图拥有的工具名集合
                        如 booking 子图：
                        {'book_seat_tool', 'search_free_seats_tool', 'get_my_info_tool'}

    Returns:
        过滤后的消息列表。保留规则汇总：
        - SystemMessage 全留
        - HumanMessage 仅当"末尾 / 无回答 / 至少有一条回答幸存"时留
        - AIMessage(含 tool_calls) 仅当所有 tool_call 属于本子图时留
        - AIMessage(纯文本) 仅当上一条不是其他子图 ToolMessage 时留
        - ToolMessage 仅当 tool_call_id 属于本子图时留
    """
    stage1 = _filter_foreign_tool_chains(messages, own_tool_names)
    stage2 = _drop_orphan_human_messages(messages, stage1)
    return stage2