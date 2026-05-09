# mcp_server/server.py
import json
import sqlite3
import os
import uuid
from mcp.server.fastmcp import FastMCP

# 1. 实例化 MCP 服务器
mcp = FastMCP("DreamRoom_MCP")

# 2. 数据库连接辅助函数
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(CURRENT_DIR, "dream_room.db")


def get_db():
    """获取数据库连接，并设置返回结果为字典格式（更易读）"""
    conn = sqlite3.connect(DB_PATH, timeout=30)  # ⭐ timeout从10提到30秒
    conn.row_factory = sqlite3.Row
    # ⭐ 开启 WAL 模式：读写并发不互锁，从根本上减少 database is locked  预写式日志
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")  # 锁等待30秒再报错
    return conn

# ==========================================
# 3. 定义大模型可以调用的 Tools
# ⭐ 改进点：所有返回值统一为标准 JSON 字符串
# ==========================================

@mcp.tool()
def get_user_info(student_id: str) -> str:
    """查询用户的当前积分和违约次数。预约前通常需要调用此工具核实用户身份。"""
    try:
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE student_id = ?", (student_id,)).fetchone()
            if not user:
                return json.dumps({
                    "success": False,
                    "error_code": "USER_NOT_FOUND",
                    "message": f"查无此人: 学号 {student_id}"
                }, ensure_ascii=False)

            return json.dumps({
                "success": True,
                "data": {
                    "name": user['name'],
                    "student_id": user['student_id'],
                    "points": user['points'],
                    "violation_count": user['violation_count']
                }
            }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "error_code": "DB_ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool()
def search_free_seats(zone_type: str = None) -> str:
    """查询当前空闲的座位。zone_type 可以是 '静音区' 或 '讨论区'，如果不传则查询所有空闲座位。"""
    try:
        with get_db() as conn:
            query = "SELECT seat_id, zone_type FROM seats WHERE status = 'FREE'"
            params = []
            if zone_type:
                query += " AND zone_type = ?"
                params.append(zone_type)

            seats = conn.execute(query, params).fetchall()

            if not seats:
                return json.dumps({
                    "success": True,
                    "data": [],
                    "message": "目前没有符合条件的空闲座位了"
                }, ensure_ascii=False)

            # 将每一行数据转为字典，组装成列表
            seat_list = [{"seat_id": s['seat_id'], "zone_type": s['zone_type']} for s in seats]

            return json.dumps({
                "success": True,
                "data": seat_list
            }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "error_code": "DB_ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool()
def book_seat_transaction(student_id: str, seat_id: int, duration: int) -> str:
    """核心事务：执行自习室座位预约预定。"""
    if duration <= 0 or duration > 8:
        return json.dumps({
            "success": False,
            "error_code": "INVALID_PARAM",
            "message": "时长必须在 1 到 8 小时之间"
        }, ensure_ascii=False)

    try:
        with get_db() as conn:
            user = conn.execute("SELECT violation_count FROM users WHERE student_id = ?", (student_id,)).fetchone()
            if not user:
                return json.dumps({"success": False, "error_code": "USER_NOT_FOUND", "message": "查无此人"},
                                  ensure_ascii=False)
            if user['violation_count'] >= 3:
                return json.dumps({"success": False, "error_code": "VIOLATION_LIMIT", "message": "本月违约已达3次"},
                                  ensure_ascii=False)

            booking_id = f"BKG_{uuid.uuid4().hex[:8].upper()}"

            # 核心防超卖逻辑：基于乐观锁的原子更新 (CAS)
            cursor = conn.execute(
                "UPDATE seats SET status = 'OCCUPIED' WHERE seat_id = ? AND status = 'FREE'",
                (seat_id,)
            )

            if cursor.rowcount == 0:
                # CAS 失败有两种语义不同的可能，必须区分：
                # 1. 座位根本不存在 -> invalid_params（参数错误）
                # 2. 座位存在但被占用 -> resource_conflict（资源冲突）
                seat_check = conn.execute("SELECT seat_id FROM seats WHERE seat_id = ?", (seat_id,)).fetchone()
                if not seat_check:
                    return json.dumps({
                        "success": False,
                        "error_code": "SEAT_NOT_FOUND",
                        "message": f"座位号 {seat_id} 不存在，请重新选择有效座位"
                    }, ensure_ascii=False)
                return json.dumps({
                    "success": False,
                    "error_code": "SEAT_OCCUPIED",
                    "message": f"座位 {seat_id} 当前已被占用"
                }, ensure_ascii=False)

            conn.execute(
                "INSERT INTO bookings (booking_id, student_id, seat_id, duration, status) VALUES (?, ?, ?, ?, 'LOCKED')",
                (booking_id, student_id, seat_id, duration)
            )

        return json.dumps({
            "success": True,
            "data": {
                "booking_id": booking_id,
                "student_id": student_id,
                "seat_id": seat_id,
                "duration": duration
            }
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error_code": "DB_SYSTEM_ERROR",
            "message": f"底层数据库异常: {str(e)}"
        }, ensure_ascii=False)


# ==========================================
# 4. 启动服务
# ==========================================
if __name__ == "__main__":
    mcp.run(transport='stdio')