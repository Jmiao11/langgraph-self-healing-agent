# test/test_session_registry_l1.py
"""
L1 纯函数测试：SessionRegistry。零依赖、不连网、不需事件循环。
覆盖会话注册表的命脉——归属隔离（IDOR 防护）、静默拒绝、时间序、幂等建表。

⭐ 安全即测试：把「非归属者读不到 / 改不动 / 探测不出」固化成回归，
   与 L1 里 unrecoverable 模板的「禁止泄露」测试是同一种纪律。
"""
import pytest

from services.session_registry import SessionRegistry


@pytest.fixture
def registry(tmp_path):
    """每个测试一个全新的临时 db，互不污染。"""
    return SessionRegistry(str(tmp_path / "sessions.db"))


# ==========================================
# 1. 基础 CRUD
# ==========================================
class TestBasicCrud:

    def test_create_then_get(self, registry):
        s = registry.create_session("stu_A", "tid-1", title="预定座位")
        assert s is not None
        assert s["thread_id"] == "tid-1"
        assert s["user_id"] == "stu_A"
        assert s["title"] == "预定座位"
        # created_at / updated_at 初始相等
        assert s["created_at"] == s["updated_at"]

    def test_create_is_idempotent(self, registry):
        """同一 thread_id 重复登记 → 只有一行（PRIMARY KEY + INSERT OR IGNORE）。"""
        registry.create_session("stu_A", "tid-1", title="first")
        registry.create_session("stu_A", "tid-1", title="second")  # 应被忽略
        sessions = registry.list_sessions("stu_A")
        assert len(sessions) == 1
        # 标题仍是首次的，第二次没覆盖
        assert sessions[0]["title"] == "first"

    def test_get_unknown_returns_none(self, registry):
        assert registry.get_session("stu_A", "no-such-thread") is None


# ==========================================
# 2. 归属隔离 & IDOR 静默拒绝（核心安全）
# ==========================================
class TestOwnershipIsolation:

    def test_list_only_returns_own_sessions(self, registry):
        registry.create_session("stu_A", "tid-A1")
        registry.create_session("stu_A", "tid-A2")
        registry.create_session("stu_B", "tid-B1")
        a_threads = {s["thread_id"] for s in registry.list_sessions("stu_A")}
        b_threads = {s["thread_id"] for s in registry.list_sessions("stu_B")}
        assert a_threads == {"tid-A1", "tid-A2"}
        assert b_threads == {"tid-B1"}

    def test_verify_owner_true_for_owner(self, registry):
        registry.create_session("stu_A", "tid-1")
        assert registry.verify_owner("stu_A", "tid-1") is True

    def test_verify_owner_false_for_non_owner(self, registry):
        """⭐ IDOR 闸门：B 不能凭 thread_id 通过 A 的会话归属校验。"""
        registry.create_session("stu_A", "tid-1")
        assert registry.verify_owner("stu_B", "tid-1") is False

    def test_verify_owner_false_for_unknown_thread(self, registry):
        assert registry.verify_owner("stu_A", "ghost-thread") is False

    def test_get_session_silent_deny_for_non_owner(self, registry):
        """⭐ 静默拒绝：非归属者 get 得到 None，与「不存在」无法区分（杜绝探测）。"""
        registry.create_session("stu_A", "tid-1")
        # B 看 A 的真实会话 → None；B 看根本不存在的会话 → 也是 None。两者一致。
        assert registry.get_session("stu_B", "tid-1") is None
        assert registry.get_session("stu_B", "ghost") is None


# ==========================================
# 3. touch & 时间序
# ==========================================
class TestTouchAndOrdering:

    def test_touch_updates_updated_at(self, registry):
        registry.create_session("stu_A", "tid-1", now="2024-01-01T00:00:00+00:00")
        ok = registry.touch("stu_A", "tid-1", now="2024-01-02T00:00:00+00:00")
        assert ok is True
        s = registry.get_session("stu_A", "tid-1")
        # created_at 不动，updated_at 前移
        assert s["created_at"] == "2024-01-01T00:00:00+00:00"
        assert s["updated_at"] == "2024-01-02T00:00:00+00:00"

    def test_touch_non_owner_is_noop(self, registry):
        """⭐ 非归属者 touch 是静默 no-op：返回 False 且不改动原记录。"""
        registry.create_session("stu_A", "tid-1", now="2024-01-01T00:00:00+00:00")
        ok = registry.touch("stu_B", "tid-1", now="2099-01-01T00:00:00+00:00")
        assert ok is False
        # A 的记录未被 B 篡改
        s = registry.get_session("stu_A", "tid-1")
        assert s["updated_at"] == "2024-01-01T00:00:00+00:00"

    def test_touch_unknown_returns_false(self, registry):
        assert registry.touch("stu_A", "ghost-thread") is False

    def test_list_ordered_by_updated_desc(self, registry):
        """列举按 updated_at 倒序：最近活跃的会话排最前。"""
        registry.create_session("stu_A", "old", now="2024-01-01T00:00:00+00:00")
        registry.create_session("stu_A", "mid", now="2024-02-01T00:00:00+00:00")
        registry.create_session("stu_A", "new", now="2024-03-01T00:00:00+00:00")
        order = [s["thread_id"] for s in registry.list_sessions("stu_A")]
        assert order == ["new", "mid", "old"]

    def test_touch_reorders_list(self, registry):
        """touch 一条旧会话后，它应跃居列表最前（最近活跃）。"""
        registry.create_session("stu_A", "old", now="2024-01-01T00:00:00+00:00")
        registry.create_session("stu_A", "new", now="2024-02-01T00:00:00+00:00")
        # 把 old touch 到最新
        registry.touch("stu_A", "old", now="2024-03-01T00:00:00+00:00")
        order = [s["thread_id"] for s in registry.list_sessions("stu_A")]
        assert order == ["old", "new"]


# ==========================================
# 4. 建表幂等性
# ==========================================
class TestSchemaIdempotent:

    def test_reinit_same_path_is_safe(self, tmp_path):
        """对同一路径重复实例化（重复建表）不报错，且已有数据不丢。"""
        path = str(tmp_path / "sessions.db")
        r1 = SessionRegistry(path)
        r1.create_session("stu_A", "tid-1")
        # 第二次实例化会再跑一遍 _init_schema —— 必须幂等
        r2 = SessionRegistry(path)
        assert r2.verify_owner("stu_A", "tid-1") is True