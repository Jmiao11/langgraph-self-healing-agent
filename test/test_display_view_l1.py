# test/test_display_view_l1.py
"""
L1 纯函数测试：build_display_view。零依赖、不连网。
覆盖「展示视图」过滤的命脉——剥离系统提示词/工具噪音，只留人类可见对话。

⭐ 安全即测试：把「SystemMessage（身份守卫/指令）绝不泄露到前端」固化成回归。
"""
from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage,
)

from utils.message_filters import build_display_view


class TestDisplayView:

    def test_keeps_human_and_ai_text(self):
        msgs = [
            HumanMessage(content="帮我订个座位"),
            AIMessage(content="好的，已为您预定 5 号座位。"),
        ]
        view = build_display_view(msgs)
        assert view == [
            {"role": "user", "content": "帮我订个座位"},
            {"role": "assistant", "content": "好的，已为您预定 5 号座位。"},
        ]

    def test_drops_system_messages(self):
        """⭐ 身份守卫 / 指令 SystemMessage 绝不能出现在展示视图（防提示词泄露）。"""
        msgs = [
            SystemMessage(content="【系统底层强制安全指令】学号 stu_A ..."),
            HumanMessage(content="你好"),
            SystemMessage(content="【系统诊断】资源冲突 ..."),  # error_analyzer 指令
            AIMessage(content="您好，有什么可以帮您？"),
        ]
        view = build_display_view(msgs)
        assert view == [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好，有什么可以帮您？"},
        ]
        # 双保险：任何一条 content 都不应包含系统提示词关键词
        assert all("系统底层" not in v["content"] for v in view)
        assert all("系统诊断" not in v["content"] for v in view)

    def test_drops_tool_messages(self):
        msgs = [
            HumanMessage(content="查我的积分"),
            ToolMessage(content="积分100, 违约0", name="get_my_info_tool", tool_call_id="t:1"),
            AIMessage(content="您当前积分 100，无违约记录。"),
        ]
        view = build_display_view(msgs)
        assert view == [
            {"role": "user", "content": "查我的积分"},
            {"role": "assistant", "content": "您当前积分 100，无违约记录。"},
        ]

    def test_drops_ai_tool_call_only(self):
        """只含 tool_calls、无可见文本的中间 AIMessage → 丢弃。"""
        ai_toolcall = AIMessage(
            content="",
            tool_calls=[{"name": "book_seat_tool", "args": {"seat_id": 5}, "id": "t:1"}],
        )
        msgs = [
            HumanMessage(content="订 5 号"),
            ai_toolcall,
            ToolMessage(content="✅ 预定成功", name="book_seat_tool", tool_call_id="t:1"),
            AIMessage(content="已为您预定 5 号座位。"),
        ]
        view = build_display_view(msgs)
        assert view == [
            {"role": "user", "content": "订 5 号"},
            {"role": "assistant", "content": "已为您预定 5 号座位。"},
        ]

    def test_keeps_ai_with_content_even_if_tool_calls(self):
        """既有文本又有 tool_calls 的 AIMessage → 保留文本部分。"""
        ai = AIMessage(
            content="正在为您查询空座……",
            tool_calls=[{"name": "search_free_seats_tool", "args": {}, "id": "t:1"}],
        )
        view = build_display_view([HumanMessage(content="有空座吗"), ai])
        assert view == [
            {"role": "user", "content": "有空座吗"},
            {"role": "assistant", "content": "正在为您查询空座……"},
        ]

    def test_order_preserved(self):
        msgs = [
            HumanMessage(content="一"),
            AIMessage(content="1"),
            HumanMessage(content="二"),
            AIMessage(content="2"),
        ]
        view = build_display_view(msgs)
        assert [v["content"] for v in view] == ["一", "1", "二", "2"]

    def test_whitespace_only_content_dropped(self):
        """纯空白文本视为无内容，丢弃。"""
        msgs = [
            HumanMessage(content="问题"),
            AIMessage(content="   \n  "),  # 空白
        ]
        view = build_display_view(msgs)
        assert view == [{"role": "user", "content": "问题"}]

    def test_multimodal_content_extracted(self):
        """content 为多模态 block 列表时，提取其中 text 块。"""
        ai = AIMessage(content=[{"type": "text", "text": "这是答案"}])
        view = build_display_view([ai])
        assert view == [{"role": "assistant", "content": "这是答案"}]

    def test_empty_input(self):
        assert build_display_view([]) == []