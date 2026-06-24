# mcp_server/init_db.py
import sqlite3
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(CURRENT_DIR, "dream_room.db")


def init_database():
    print(f"🛠️ 正在初始化物理关系型数据库: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # ⭐ 持久化的 PRAGMA 设置
        cursor.execute("PRAGMA journal_mode=WAL;")

        # 1. 创建用户表 (解决 no such table: users 的元凶)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                student_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                password TEXT NOT NULL,
                points INTEGER DEFAULT 100,
                violation_count INTEGER DEFAULT 0
            )
        ''')

        # 2. 创建座位表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS seats (
                seat_id INTEGER PRIMARY KEY,
                zone_type TEXT NOT NULL,
                status TEXT DEFAULT 'FREE' CHECK(status IN ('FREE', 'OCCUPIED'))
            )
        ''')

        # 3. 创建订单表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                booking_id TEXT PRIMARY KEY,
                student_id TEXT,
                seat_id INTEGER,
                duration INTEGER,
                status TEXT,
                FOREIGN KEY(student_id) REFERENCES users(student_id),
                FOREIGN KEY(seat_id) REFERENCES seats(seat_id)
            )
        ''')

        # 4. 注入测试数据 (清理旧数据防冲突)
        cursor.execute("DELETE FROM users")
        cursor.execute("DELETE FROM seats")

        # 注入你的测试账号
        cursor.execute(
            "INSERT INTO users (student_id, name, password, violation_count) VALUES ('stu001', '沈建大图情测试员', '123', 0)")
        cursor.execute(
            "INSERT INTO users (student_id, name, password, violation_count) VALUES ('stu_bad', '违规大王', '123', 5)")

        # ⭐ 座位池：三区分布，编号区码化（1xx 讨论 / 2xx 算力，静音从 1 起以保住测试锚点 1/2）
        # 占用规则：锚点 1/2 强制 OCCUPIED（对应下方测试订单）；其余 seat_id % 3 == 0 视为他人占用，
        #          余下 FREE。纯规则、不用 random → 每次 init 结果一致，演示/截图可复现。
        ZONE_RANGES = [
            ("静音区", range(1, 41)),     # 1–40
            ("讨论区", range(101, 121)),  # 101–120
            ("算力区", range(201, 213)),  # 201–212
        ]
        ANCHOR_OCCUPIED = {1, 2}  # 绑定 BKG_TEST 订单，必须保持 OCCUPIED
        test_seats = []
        for zone_name, id_range in ZONE_RANGES:
            for sid in id_range:
                occupied = sid in ANCHOR_OCCUPIED or sid % 3 == 0
                test_seats.append((sid, zone_name, "OCCUPIED" if occupied else "FREE"))
        cursor.executemany("INSERT INTO seats (seat_id, zone_type, status) VALUES (?, ?, ?)", test_seats)
        _occupied = sum(1 for _s in test_seats if _s[2] == "OCCUPIED")
        print(f"   - 座位池：{len(test_seats)} 座（静音区 40 / 讨论区 20 / 算力区 12），占用 {_occupied} 座")

        # ⭐ CRUD 测试数据：预置几条订单以便测试 Read/Update/Delete
        # - BKG_TEST0001: stu001 的活跃订单（可测试 cancel / update）
        # - BKG_TEST0002: stu_bad 的订单（用于测试 NOT_YOUR_BOOKING 越权场景）
        cursor.execute("DELETE FROM bookings")  # 清理旧数据
        test_bookings = [
            ('BKG_TEST0001', 'stu001', 1, 2, 'LOCKED'),  # stu001 占用座位 1，时长 2h
            ('BKG_TEST0002', 'stu_bad', 2, 3, 'LOCKED'),  # stu_bad 占用座位 2，时长 3h
        ]
        cursor.executemany(
            "INSERT INTO bookings (booking_id, student_id, seat_id, duration, status) VALUES (?, ?, ?, ?, ?)",
            test_bookings
        )

        conn.commit()
        print("✅ 物理数据库建表与测试数据注入成功！")
        print("   - 预置订单 BKG_TEST0001 (stu001)：用于测试 cancel/update")
        print("   - 预置订单 BKG_TEST0002 (stu_bad)：用于测试越权防护")
        print("✅ 物理数据库建表与测试数据注入成功！")


if __name__ == "__main__":
    init_database()