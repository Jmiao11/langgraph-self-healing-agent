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

        # 注入几个测试座位
        test_seats = [
            (1, '静音区', 'FREE'),
            (2, '静音区', 'FREE'),
            (3, '讨论区', 'FREE'),
            (210, '算力区', 'FREE')
        ]
        cursor.executemany("INSERT INTO seats (seat_id, zone_type, status) VALUES (?, ?, ?)", test_seats)

        conn.commit()
        print("✅ 物理数据库建表与测试数据注入成功！")


if __name__ == "__main__":
    init_database()