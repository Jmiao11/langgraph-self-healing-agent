# app
import streamlit as st
import requests
import uuid

API_BASE = "http://127.0.0.1:8000"

# 页面基础设置
st.set_page_config(page_title="梦想自习室 AI 馆员", page_icon="📚", layout="wide")

# --- 初始化状态 ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "student_id" not in st.session_state:
    st.session_state.student_id = None
if "user_name" not in st.session_state:
    st.session_state.user_name = None
if "token" not in st.session_state:
    st.session_state.token = None
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []


# ==========================================
# 数据拉取（只读端点）
# ==========================================
def _auth_headers():
    return {"Authorization": f"Bearer {st.session_state.token}"}


def fetch_seats():
    """拉取全部座位状态。失败返回 None（前端降级处理）。"""
    try:
        res = requests.get(f"{API_BASE}/api/seats", headers=_auth_headers(), timeout=5)
        if res.status_code == 200:
            return res.json().get("data", [])
    except requests.exceptions.RequestException:
        pass
    return None


def fetch_my_bookings():
    """拉取当前用户订单。失败返回 None。"""
    try:
        res = requests.get(f"{API_BASE}/api/my-bookings", headers=_auth_headers(), timeout=5)
        if res.status_code == 200:
            return res.json().get("data", [])
    except requests.exceptions.RequestException:
        pass
    return None


# ==========================================
# 渲染组件
# ==========================================
STATUS_LABEL = {"LOCKED": "🟢 进行中", "CANCELLED": "⚪ 已取消"}


def render_my_bookings_sidebar():
    """侧边栏：我的订单列表。"""
    st.divider()
    st.subheader("📋 我的订单")
    bookings = fetch_my_bookings()

    if bookings is None:
        st.caption("⚠️ 订单数据加载失败")
        return
    if not bookings:
        st.caption("暂无订单")
        return

    for b in bookings:
        label = STATUS_LABEL.get(b["status"], b["status"])
        zone = b.get("zone_type") or "未知区域"
        st.markdown(
            f"**{b['booking_id']}** &nbsp; {label}\n\n"
            f"📍 {zone} · 座位 {b['seat_id']} · {b['duration']}h"
        )


def _render_seat_zones(seats, expanded_in_page=False):
    """共享的座位网格渲染（按区域分组 + CSS Grid）。
    expanded_in_page=True 时直接铺在页面上，不套 expander。"""
    zones = {}
    for s in seats:
        zones.setdefault(s["zone_type"], []).append(s)

    st.caption("🟦 我的座位 ｜ 🟩 空闲 ｜ ⬛ 已占用（他人）")

    parts = ['<div style="display:flex;flex-direction:column;gap:14px;">']
    for zone_name, zone_seats in zones.items():
        parts.append(
            f'<div style="font-weight:600;color:#c9d1d9;font-size:15px;">{zone_name}</div>'
        )
        parts.append(
            '<div style="display:grid;'
            'grid-template-columns:repeat(auto-fill,minmax(88px,1fr));gap:10px;">'
        )
        for s in zone_seats:
            if s["is_mine"]:
                bg, border, color, tag = "#1f6feb", "#1f6feb", "#ffffff", "我的"
            elif s["status"] == "FREE":
                bg, border, color, tag = "#0d1117", "#2ea043", "#7ee787", "空闲"
            else:
                bg, border, color, tag = "#161b22", "#6e7681", "#8b949e", "已占"
            parts.append(
                f'<div style="background:{bg};border:1px solid {border};'
                f'border-radius:8px;padding:10px 6px;text-align:center;color:{color};">'
                f'<div style="font-size:18px;font-weight:700;line-height:1.3;">{s["seat_id"]}</div>'
                f'<div style="font-size:12px;opacity:0.85;">{tag}</div>'
                f'</div>'
            )
        parts.append('</div>')
    parts.append('</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)

def render_seat_grid():
    """主区顶部：实时座位网格，CSS Grid 渲染，自己的座位高亮。"""
    with st.expander("🪑 实时座位状态", expanded=True):
        seats = fetch_seats()

        if seats is None:
            st.warning("座位数据加载失败，请检查后端服务")
            return
        if not seats:
            st.info("暂无座位数据")
            return

        # 按区域分组
        zones = {}
        for s in seats:
            zones.setdefault(s["zone_type"], []).append(s)

        st.caption("🟦 我的座位 ｜ 🟩 空闲 ｜ ⬛ 已占用（他人）")

        # ⭐ 用单段 CSS Grid 一次性渲染：卡片自动等宽等高、紧凑换行，
        #    不受 st.columns 在 expander 内的 gap/最小宽行为影响
        parts = ['<div style="display:flex;flex-direction:column;gap:14px;">']
        for zone_name, zone_seats in zones.items():
            parts.append(
                f'<div style="font-weight:600;color:#c9d1d9;font-size:15px;">{zone_name}</div>'
            )
            parts.append(
                '<div style="display:grid;'
                'grid-template-columns:repeat(auto-fill,minmax(88px,1fr));gap:10px;">'
            )
            for s in zone_seats:
                if s["is_mine"]:
                    bg, border, color, tag = "#1f6feb", "#1f6feb", "#ffffff", "我的"
                elif s["status"] == "FREE":
                    bg, border, color, tag = "#0d1117", "#2ea043", "#7ee787", "空闲"
                else:  # OCCUPIED 他人
                    bg, border, color, tag = "#161b22", "#6e7681", "#8b949e", "已占"
                parts.append(
                    f'<div style="background:{bg};border:1px solid {border};'
                    f'border-radius:8px;padding:10px 6px;text-align:center;color:{color};">'
                    f'<div style="font-size:18px;font-weight:700;line-height:1.3;">{s["seat_id"]}</div>'
                    f'<div style="font-size:12px;opacity:0.85;">{tag}</div>'
                    f'</div>'
                )
            parts.append('</div>')
        parts.append('</div>')

        # ⭐ 必须 "".join 不留换行——Streamlit 的 markdown 会把空行解释成段落分隔，
        #    破坏 HTML 结构
        st.markdown("".join(parts), unsafe_allow_html=True)


def render_seat_panel_page():
    """座位面板独立页：顶部汇总统计 + 座位网格。"""
    st.title("🪑 座位面板")

    seats = fetch_seats()
    if seats is None:
        st.warning("座位数据加载失败，请检查后端服务")
        return
    if not seats:
        st.info("暂无座位数据")
        return

    # --- 顶部汇总统计 ---
    total = len(seats)
    free = sum(1 for s in seats if s["status"] == "FREE")
    mine = sum(1 for s in seats if s["is_mine"])
    occupied_others = total - free - mine

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("座位总数", total)
    c2.metric("空闲", free)
    c3.metric("我的座位", mine)
    c4.metric("他人占用", occupied_others)

    st.divider()

    # --- 座位网格（复用渲染逻辑，独立页不套 expander）---
    _render_seat_zones(seats, expanded_in_page=True)


# ==========================================
# 1. 登录逻辑（不动）
# ==========================================
if not st.session_state.logged_in:
    st.title("🔐 梦想自习室 - 身份认证")
    st.info("提示：测试账号 stu001 / 密码 123")

    with st.form("login"):
        input_id = st.text_input("学号")
        input_pwd = st.text_input("密码", type="password")
        if st.form_submit_button("登录"):
            try:
                res = requests.post(
                    f"{API_BASE}/api/login",
                    json={"student_id": input_id, "password": input_pwd}
                )
                if res.status_code == 200:
                    user_data = res.json()
                    st.session_state.logged_in = True
                    st.session_state.student_id = input_id
                    st.session_state.user_name = user_data["name"]
                    st.session_state.token = user_data["token"]
                    st.rerun()
                else:
                    st.error("学号或密码错误")
            except requests.exceptions.RequestException:
                st.error("后端 API 服务未启动或网络连接失败")

# ==========================================
# 2. 主界面：侧边栏导航 + 双视图
# ==========================================
else:
    # --- 侧边栏：用户信息 + 视图导航 ---
    with st.sidebar:
        st.success(f"已登录: {st.session_state.user_name}")
        st.write(f"学号: {st.session_state.student_id}")

        st.divider()
        # ⭐ 视图导航：聊天 / 座位面板
        view = st.radio(
            "导航",
            ["💬 AI 馆员", "🪑 座位面板"],
            label_visibility="collapsed",
        )

        if st.button("🔄 刷新数据", use_container_width=True):
            st.rerun()
        if st.button("退出登录", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.messages = []
            st.session_state.token = None
            st.rerun()

        # 聊天视图下，侧边栏保留「我的订单」摘要；
        # 座位面板视图下不重复展示（面板里有完整数据）
        if view == "💬 AI 馆员":
            render_my_bookings_sidebar()

    # ==========================================
    # 视图 A：座位面板（独立页）
    # ==========================================
    if view == "🪑 座位面板":
        render_seat_panel_page()

    # ==========================================
    # 视图 B：AI 馆员聊天
    # ==========================================
    else:
        st.title("📚 AI 馆员在线中")

        # 渲染历史
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # ⭐ chat_input 必须在页面顶层（不进 expander/columns/tabs），
        #    用 if 条件渲染而非容器包裹，规避底部钉死坑
        if prompt := st.chat_input("您可以直接说：帮我定个静音区的座"):
            with st.chat_message("user"):
                st.markdown(prompt)
            st.session_state.messages.append({"role": "user", "content": prompt})

            with st.chat_message("assistant"):
                with st.spinner("AI 馆员正在同步数据库信息..."):
                    try:
                        payload = {
                            "thread_id": st.session_state.thread_id,
                            "message": prompt,
                            "student_id": st.session_state.student_id,
                            "user_name": st.session_state.user_name
                        }
                        res = requests.post(
                            f"{API_BASE}/api/chat",
                            json=payload,
                            headers=_auth_headers()
                        )
                        if res.status_code == 200:
                            ans = res.json().get("response")
                            st.markdown(ans)
                            st.session_state.messages.append({"role": "assistant", "content": ans})
                            # 对话可能改变座位/订单 → rerun 让侧边栏订单刷新
                            st.rerun()
                        else:
                            st.error("后端连接失败")
                    except requests.exceptions.RequestException:
                        st.error("网络异常，请确保 API 已启动")

# streamlit run app.py