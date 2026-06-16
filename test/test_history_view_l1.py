# test/test_history_view_l1.py
"""
L1 纯函数测试：build_history_view_or_none（归属闸门 + 展示过滤）。
零依赖、不连网、不需真实图。

⭐ 核心安全断言：归属不成立时，函数在「读消息之前」就返回 None——
   证明非归属者拿不到任何消息片段（IDOR 短路）。
"""
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from utils.message_filters import build_history_view_or_none


class _FakeRegistry:
    """鸭子类型的假 registry，只实现 verify_owner。
    记录是否被调用，便于断言短路顺序。"""
    def __init__(self, owner_map: dict):
        self.owner_map = owner_map           # {(user_id, thread_id): bool}
        self.verify_calls = 0

    def verify_owner(self, user_id: str, thread_id: str) -> bool:
        self.verify_calls += 1
        return self.owner_map.get((user_id, thread_id), False)


def _snapshot_with_messages():
    return {
        "messages": [
            SystemMessage(content="【系统底层强制安全指令】..."),
            HumanMessage(content="订个座位"),
            AIMessage(content="已为您预定 5 号。"),
        ]
    }


class TestHistoryGate:

    def test_owner_gets_filtered_view(self):
        """归属成立 → 返回过滤后的展示视图（剥掉 SystemMessage）。"""
        reg = _FakeRegistry({("stu_A", "tid-1"): True})
        view = build_history_view_or_none(reg, _snapshot_with_messages(), "stu_A", "tid-1")
        assert view == [
            {"role": "user", "content": "订个座位"},
            {"role": "assistant", "content": "已为您预定 5 号。"},
        ]
        # 系统提示词没泄露
        assert all("系统底层" not in v["content"] for v in view)

    def test_non_owner_gets_none(self):
        """⭐ 归属不成立 → None，且根本不返回任何消息内容。"""
        reg = _FakeRegistry({("stu_A", "tid-1"): True})  # 只有 A 拥有
        view = build_history_view_or_none(reg, _snapshot_with_messages(), "stu_B", "tid-1")
        assert view is None
        assert reg.verify_calls == 1  # 闸门被调用过

    def test_unknown_thread_gets_none(self):
        reg = _FakeRegistry({})  # 谁都不拥有
        view = build_history_view_or_none(reg, _snapshot_with_messages(), "stu_A", "ghost")
        assert view is None

    def test_none_snapshot_values_yields_empty(self):
        """归属成立但 snapshot 为 None（无 checkpoint）→ 空列表，不崩。"""
        reg = _FakeRegistry({("stu_A", "tid-1"): True})
        view = build_history_view_or_none(reg, None, "stu_A", "tid-1")
        assert view == []

    def test_missing_messages_key_yields_empty(self):
        """归属成立但 values 里没 messages 键 → 空列表。"""
        reg = _FakeRegistry({("stu_A", "tid-1"): True})
        view = build_history_view_or_none(reg, {}, "stu_A", "tid-1")
        assert view == []