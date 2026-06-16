# services/session_registry.py
"""
会话注册表 (Session Registry)
==============================

职责：维护「用户 → 他拥有哪些会话」的应用层元数据。

⭐ 为什么需要它（设计动机，面试必答）：
LangGraph 的 checkpointer（AsyncSqliteSaver / memory.db）只按 thread_id 持久化
图的内部状态快照，它**不知道 user 是谁**，也没有 title / 时间这类业务元数据。
因此单靠 checkpointer 无法做到两件产品级的事：
  1. 「按用户列举他的全部会话」——checkpointer 表里没有 user 维度
  2. 「给会话一个人看得懂的标题和时间」——那是业务元数据，不属于图状态

所以这是**第二张独立的表**，thread_id 作为它与 checkpointer 之间的 join key。
这与项目既有的两条纪律一脉相承：
  - CQRS 读写分离：registry 是「读模型」，checkpointer 是写时落下的引擎状态
  - 承重墙 / 开闭原则：新能力 = 新模块新表，绝不改图签名或 pipeline

⭐ 安全（IDOR 防护，与订单越权防护同源）：
所有「针对单条会话」的操作（verify_owner / get / touch）都以 user_id 作为查询
条件的一部分。非归属者得到的是「空 / False」，与「不存在」**无法区分**——这是
静默拒绝，杜绝攻击者借 thread_id 探测会话存在性。这与 DB 层「存在→归属→状态」
三段校验、与 NotYourBookingError 选 UNRECOVERABLE 的安全哲学完全一致。

⭐ 同步 SQLite 的取舍：
本模块用同步 sqlite3（与 api.py 既有的 get_readonly_db 只读端点同款），而非
aiosqlite。理由：会话元数据查询都是毫秒级小查询，同步实现更简单、L1 单测无需
事件循环即可纯函数式验证。db 路径走依赖注入，若未来并发压力要求非阻塞，替换为
aiosqlite 仅影响本文件，上层无感。
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    """当前 UTC 时间的 ISO8601 字符串（统一时间格式，便于排序与跨时区展示）。"""
    return datetime.now(timezone.utc).isoformat()


class SessionRegistry:
    """会话注册表。一个用户可拥有多条会话，一条会话对应一个 thread_id。"""

    def __init__(self, db_path: str):
        """
        Args:
            db_path: registry 数据库文件路径（依赖注入，便于测试传 tmp 路径）。
        """
        self.db_path = db_path
        # 确保父目录存在（与 checkpointer 的 data/memory 同目录策略一致）
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self._init_schema()

    # ==========================================
    # 连接 & 建表
    # ==========================================
    @contextmanager
    def _conn(self):
        """每次操作开一条短连接（与 get_readonly_db 同款），用完即关。
        sqlite3 连接的上下文管理器只负责 commit/rollback，不负责 close，
        因此这里显式 try/finally 关闭。"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """幂等建表 + 建索引。重复调用安全（IF NOT EXISTS）。"""
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    thread_id   TEXT PRIMARY KEY,        -- 与 checkpointer 的 join key；
                                                         -- PRIMARY KEY 物理保证一 thread 一行
                    user_id     TEXT NOT NULL,           -- 归属：会话属于哪个学号
                    title       TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL,           -- ISO8601 UTC
                    updated_at  TEXT NOT NULL
                )
                """
            )
            # 列举查询走 (user_id, updated_at DESC)：按用户过滤 + 按最近活跃排序
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_user
                ON chat_sessions(user_id, updated_at DESC)
                """
            )

    # ==========================================
    # 写
    # ==========================================
    def create_session(
        self,
        user_id: str,
        thread_id: str,
        title: str = "",
        now: str | None = None,
    ) -> dict:
        """登记一条新会话。

        幂等：thread_id 已存在则不重复插入（INSERT OR IGNORE）。这防止「同一 thread
        被登记两次」破坏 PRIMARY KEY；且因 thread_id 由 UUID 生成、碰撞概率可忽略，
        OR IGNORE 仅作防御。归属冲突（别人已占用该 thread_id）也会被静默忽略，
        不会发生「A 把 B 的会话改成自己的」。

        Args:
            now: 注入时钟（默认 None → 取当前 UTC）。注入便于单测确定性验证时间序，
                 与 analyze_error 注入 llm / max_attempts 是同一种可测试性设计。
        Returns:
            该会话的当前记录（dict）。若因已存在而未插入，返回库中已有的那条。
        """
        ts = now or _utc_now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_sessions
                    (thread_id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (thread_id, user_id, title, ts, ts),
            )
        # 返回归属校验过的记录（若 thread 实际属于他人，这里会拿不到 → None）
        return self.get_session(user_id, thread_id)

    def touch(self, user_id: str, thread_id: str, now: str | None = None) -> bool:
        """刷新会话的 updated_at（用户在该会话又发了一轮）。

        ⭐ 归属校验内建在 WHERE 里：UPDATE ... WHERE thread_id=? AND user_id=?。
        非归属者的 touch 是 rowcount=0 的静默 no-op，不报错、不泄露存在性。

        Returns:
            True 表示确实更新了一行（归属成立且会话存在）；False 表示没有匹配行
            （不存在 或 不属于该用户）——调用方可据此做越权防御。
        """
        ts = now or _utc_now_iso()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE thread_id = ? AND user_id = ?",
                (ts, thread_id, user_id),
            )
            return cur.rowcount > 0

    # ==========================================
    # 读（全部以 user_id 为归属边界）
    # ==========================================
    def list_sessions(self, user_id: str) -> list[dict]:
        """列举某用户的全部会话，按最近活跃倒序（最新的在最前）。"""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT thread_id, user_id, title, created_at, updated_at
                FROM chat_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, user_id: str, thread_id: str) -> dict | None:
        """读取单条会话。⭐ 归属校验内建：非归属者得到 None，与「不存在」无法区分。"""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT thread_id, user_id, title, created_at, updated_at
                FROM chat_sessions
                WHERE thread_id = ? AND user_id = ?
                """,
                (thread_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def verify_owner(self, user_id: str, thread_id: str) -> bool:
        """⭐ IDOR 授权闸门：当前用户是否拥有该会话。

        /api/history 等「按 thread_id 读历史」的端点必须先过这道闸，
        否则任何登录用户都能凭 thread_id 读他人会话（thread_id 难猜 ≠ 授权）。
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM chat_sessions WHERE thread_id = ? AND user_id = ? LIMIT 1",
                (thread_id, user_id),
            ).fetchone()
        return row is not None


# ==========================================
# ⭐ chat 轮次登记编排（纯函数，便于单测写路径的越权决策）
# ==========================================
def register_chat_turn(
    registry,
    user_id: str,
    thread_id: str,
    is_new: bool,
    title: str = "",
    now: str | None = None,
) -> bool:
    """登记本轮对话到 registry。供 /api/chat 在驱动图之前调用。

    决策逻辑（写路径的安全核心）：
      - is_new=True  → 新会话，create_session（幂等）
      - is_new=False → 老会话，必须 verify_owner 通过才 touch；
                       不通过 → 返回 False（越权：thread_id 非空但不属于该用户）

    ⭐ 越权防御：阻止有人借 /api/chat 往他人 thread 里灌消息，
       也堵死"绕过 /api/history 归属校验"的旁路。registry 为鸭子类型，
       仅需 create_session / verify_owner / touch，便于用假对象单测。

    Returns:
        True 正常放行；False 表示越权，调用方应静默拒绝（404）。
    """
    if is_new:
        registry.create_session(user_id, thread_id, title=title, now=now)
        return True
    if not registry.verify_owner(user_id, thread_id):
        return False
    registry.touch(user_id, thread_id, now=now)
    return True