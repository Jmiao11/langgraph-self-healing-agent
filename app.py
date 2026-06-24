# app
import streamlit as st
import requests
import uuid

API_BASE = "http://127.0.0.1:8000"

# 页面基础设置
st.set_page_config(page_title="梦想自习室 AI 馆员", page_icon="❖", layout="wide")

def inject_custom_css():
    st.markdown("""
        <style>
        /* ========== 1. 中文衬线字体（档案馆排版感）========== */
        /* config 的 serif 只管英文，中文需在此显式指定字体栈 */
        html, body, [class*="css"], .stMarkdown, .stMarkdown p,
        h1, h2, h3, .stButton button, .stRadio label {
            font-family: "Noto Serif SC", "Source Han Serif SC",
                         "Songti SC", "SimSun", "STSong", serif !important;
        }

        /* ========== 2. 内容区入场淡入 ========== */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .block-container {
            animation: fadeIn 0.6s ease-out forwards;
            padding-top: 3rem;
        }

        /* 透明化顶部 header，去掉机房感的横条 */
        .stApp > header { background-color: transparent !important; }

        /* ========== 3. 卡片材质：单像素边框 + 纸面阴影 + 悬浮抬起 ========== */
        /* 同时兼容新旧版 Streamlit 的 metric / expander testid */
        div[data-testid="stMetric"],
        div[data-testid="metric-container"],
        div[data-testid="stExpander"] {
            background-color: #FFFEFB;
            border: 1px solid #DED7C6;
            border-radius: 8px;
            padding: 16px;
            box-shadow: 0 1px 3px rgba(80, 60, 30, 0.04);
            transition: transform 0.25s ease, box-shadow 0.25s ease;
        }
        div[data-testid="stMetric"]:hover,
        div[data-testid="metric-container"]:hover,
        div[data-testid="stExpander"]:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 14px rgba(80, 60, 30, 0.08);
        }

        /* ========== 4. 按钮：复古红描边风，悬浮填充 ========== */
        .stButton button {
            border: 1px solid #C9B99B !important;
            border-radius: 6px !important;
            transition: all 0.25s ease !important;
        }
        .stButton button:hover {
            border-color: #7F1D1D !important;
            color: #7F1D1D !important;
        }

        /* ========== 5. 隐藏 Deploy 按钮和默认菜单，更干净 ========== */
        .stDeployButton { display: none; }
        #MainMenu { visibility: hidden; }
        </style>
    """, unsafe_allow_html=True)


# 紧跟 set_page_config 之后调用
inject_custom_css()


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
    st.session_state.thread_id = None  # ⭐ 新会话不预生成 id；后端 mint 后返回
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


def fetch_sessions():
    """拉取当前用户的会话列表（按最近活跃倒序）。失败返回空列表。"""
    try:
        res = requests.get(f"{API_BASE}/api/sessions", headers=_auth_headers(), timeout=5)
        if res.status_code == 200:
            return res.json().get("data", [])
    except requests.exceptions.RequestException:
        pass
    return []


def fetch_history(thread_id):
    """拉取某条会话的可展示历史。失败/非归属（404）返回空列表。"""
    try:
        res = requests.get(
            f"{API_BASE}/api/history",
            params={"thread_id": thread_id},
            headers=_auth_headers(),
            timeout=5,
        )
        if res.status_code == 200:
            return res.json().get("data", [])
    except requests.exceptions.RequestException:
        pass
    return []

def delete_session_api(thread_id):
    """删除一条会话。成功返回 True；404（非归属/不存在）或网络失败返回 False。"""
    try:
        res = requests.delete(
            f"{API_BASE}/api/sessions/{thread_id}",
            headers=_auth_headers(),
            timeout=5,
        )
        return res.status_code == 200
    except requests.exceptions.RequestException:
        return False

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


def render_my_bookings_page():
    """我的订单独立视图：汇总统计 + 订单卡片列表。"""
    st.title("❖ 我的订单")

    bookings = fetch_my_bookings()
    if bookings is None:
        st.warning("订单数据加载失败，请检查后端服务")
        return
    if not bookings:
        st.info("您当前还没有任何订单。去「AI 馆员」预约一个座位吧。")
        return

    # --- 顶部汇总 ---
    total = len(bookings)
    active = sum(1 for b in bookings if b["status"] == "LOCKED")
    cancelled = sum(1 for b in bookings if b["status"] == "CANCELLED")

    c1, c2, c3 = st.columns(3)
    c1.metric("订单总数", total)
    c2.metric("进行中", active)
    c3.metric("已取消", cancelled)

    st.divider()

    # --- 订单卡片列表（CSS 卡片，融入档案馆主题）---
    STATUS_BADGE = {
        "LOCKED": ("进行中", "#5C7A52", "#FFFEFB"),       # 墨绿
        "CANCELLED": ("已取消", "#8A7B5E", "#EDE7D8"),    # 灰褐沉底
    }

    parts = ['<div style="display:flex;flex-direction:column;gap:12px;">']
    for b in bookings:
        label, accent, bg = STATUS_BADGE.get(
            b["status"], (b["status"], "#8A7B5E", "#EDE7D8")
        )
        zone = b.get("zone_type") or "未知区域"
        parts.append(
            f'<div style="background:{bg};border:1px solid #DED7C6;'
            f'border-left:4px solid {accent};border-radius:8px;padding:14px 18px;'
            f'box-shadow:0 1px 2px rgba(80,60,30,0.05);'
            f'display:flex;justify-content:space-between;align-items:center;">'
            f'<div>'
            f'<div style="font-weight:700;font-size:16px;color:#2B2622;'
            f'font-family:\'Songti SC\',\'SimSun\',serif;">{b["booking_id"]}</div>'
            f'<div style="font-size:13px;color:#6B5D45;margin-top:4px;">'
            f'📍 {zone} · 座位 {b["seat_id"]} · {b["duration"]}h</div>'
            f'</div>'
            f'<div style="color:{accent};font-weight:600;font-size:14px;'
            f'white-space:nowrap;">{label}</div>'
            f'</div>'
        )
    parts.append('</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)

def _render_seat_zones(seats, expanded_in_page=False):
    """共享的座位网格渲染（按区域分组 + CSS Grid）。
    expanded_in_page=True 时直接铺在页面上，不套 expander。"""
    zones = {}
    for s in seats:
        zones.setdefault(s["zone_type"], []).append(s)

    st.caption("🟥 我的座位 ｜ 🟩 空闲 ｜ ⬜ 已占用（他人）")

    # ⭐ 档案馆配色：纸面卡片 + 复古红/墨绿/灰褐，替换原深色机房配色
    parts = ['<div style="display:flex;flex-direction:column;gap:16px;">']
    for zone_name, zone_seats in zones.items():
        parts.append(
            f'<div style="font-weight:600;color:#5C4A32;font-size:15px;'
            f'font-family:\'Songti SC\',\'SimSun\',serif;'
            f'border-left:3px solid #7F1D1D;padding-left:8px;">{zone_name}</div>'
        )
        parts.append(
            '<div style="display:grid;'
            'grid-template-columns:repeat(auto-fill,minmax(88px,1fr));gap:10px;">'
        )
        for s in zone_seats:
            if s["is_mine"]:
                # 我的座位：复古红实底，最醒目
                bg, border, color, tag = "#7F1D1D", "#7F1D1D", "#F5F1E8", "我的"
            elif s["status"] == "FREE":
                # 空闲：纸白底 + 墨绿描边
                bg, border, color, tag = "#FFFEFB", "#5C7A52", "#3D5235", "空闲"
            else:
                # 他人占用：暗米底 + 灰褐描边，沉下去
                bg, border, color, tag = "#EDE7D8", "#B8AC92", "#8A7B5E", "已占"
            parts.append(
                f'<div style="background:{bg};border:1px solid {border};'
                f'border-radius:8px;padding:10px 6px;text-align:center;color:{color};'
                f'box-shadow:0 1px 2px rgba(80,60,30,0.05);">'
                f'<div style="font-size:18px;font-weight:700;line-height:1.3;'
                f'font-family:\'Songti SC\',\'SimSun\',serif;">{s["seat_id"]}</div>'
                f'<div style="font-size:12px;opacity:0.9;">{tag}</div>'
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
    st.title("❖ 座位面板")

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


def render_session_list():
    """侧栏会话面板：新建 + 历史会话列表（点击切换）。仅在 AI 馆员视图调用。"""
    st.divider()
    st.caption("会话")

    # 新建会话：生成新 thread_id + 清空本地消息
    if st.button("➕ 新建会话", use_container_width=True):
        st.session_state.thread_id = None  # ⭐ 交给后端 mint
        st.session_state.messages = []
        st.rerun()

    sessions = fetch_sessions()
    if not sessions:
        st.caption("暂无历史会话")
        return

    for s in sessions:
        tid = s["thread_id"]
        title = (s.get("title") or "").strip() or "未命名会话"
        label = title if len(title) <= 16 else title[:16] + "…"
        is_active = (tid == st.session_state.thread_id)

        col_switch, col_del = st.columns([5, 1])
        with col_switch:
            # 当前会话：▶ 前缀 + 禁用（视觉标记、防重复点击）
            if st.button(
                    ("▶ " if is_active else "") + label,
                    key=f"sess_{tid}",
                    use_container_width=True,
                    disabled=is_active,
            ):
                # 切换会话：设 thread_id + 拉历史回填气泡
                st.session_state.thread_id = tid
                st.session_state.messages = fetch_history(tid)
                st.rerun()
        with col_del:
            if st.button("🗑", key=f"del_{tid}", use_container_width=True, help="删除此会话"):
                if delete_session_api(tid):
                    # ⭐ 删的若是当前正在看的会话 → 回到「新会话」态，避免 thread_id 悬空
                    if tid == st.session_state.thread_id:
                        st.session_state.thread_id = None
                        st.session_state.messages = []
                    st.toast("会话已删除")
                else:
                    st.toast("删除失败")
                st.rerun()

# 执行轨迹图标 → 主题色（结构符号走墨/灰褐，成败/熔断三态上色）
_TRACE_ICON_COLOR = {
    "▸": "#8A7B5E",   # 工具调用：灰褐，作步骤骨架
    "◆": "#5C7A52",   # 0-LLM 短路：墨绿（高效命中）
    "◇": "#6B5D45",   # LLM 降级：棕墨（中性）
    "⊘": "#7F1D1D",   # 熔断：复古红（危险态）
}


def render_activity_panel(activity):
    """在助手气泡下渲染「执行轨迹」可展开面板。仅当本轮有工具调用/自愈时显示。
    activity 为 /api/chat 返回的 summarize_execution_trace 结果。"""
    if not activity or not activity.get("has_activity"):
        return
    tool_calls = activity.get("tool_call_count", 0)
    shortcut = activity.get("shortcut_count", 0)
    llm_calls = activity.get("llm_classify_calls", 0)
    circuit = activity.get("circuit_broken", False)
    healing = activity.get("healing_triggered", False)
    steps = activity.get("steps", [])

    # headline：基础显工具调用次数；发生自愈时突出最亮的指标（0 LLM 短路）
    headline = f"▸ 执行轨迹 · {tool_calls} 次工具调用"
    if healing:
        if shortcut and not llm_calls:
            headline += f" · ◆ {shortcut} 次确定性短路（0 LLM）"
        elif llm_calls:
            headline += f" · ◇ {llm_calls} 次 LLM 降级分类"
    if circuit:
        headline += " · ⊘ 已熔断"

    with st.expander(headline, expanded=True):
        for step in steps:
            icon = step.get("icon", "")
            title = step.get("title", "")
            color = _TRACE_ICON_COLOR.get(icon, "#2B2622")
            # 成败标记上色：成功墨绿 / 失败复古红
            title_html = (
                title.replace("✓", '<span style="color:#5C7A52">✓</span>')
                     .replace("✕", '<span style="color:#7F1D1D">✕</span>')
            )
            st.markdown(
                f'<span style="color:{color};font-weight:700">{icon}</span> '
                f'<span style="font-weight:600">{title_html}</span>',
                unsafe_allow_html=True,
            )
            detail = step.get("detail")
            if detail:
                st.caption(detail)


# ==========================================
# 1. 登录逻辑（不动）
# ==========================================
if not st.session_state.logged_in:
    st.title("❖ 梦想自习室 · 身份认证")
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
            ["💬 AI 馆员", "🪑 座位面板", "📋 我的订单"],
            label_visibility="collapsed",
        )

        # ⭐ 会话列表：仅在 AI 馆员视图显示
        if view == "💬 AI 馆员":
            render_session_list()

        st.divider()
        if st.button("🔄 刷新数据", use_container_width=True):
            st.rerun()
        if st.button("退出登录", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.messages = []
            st.session_state.token = None
            st.rerun()


    if view == "🪑 座位面板":
        render_seat_panel_page()

    elif view == "📋 我的订单":
        render_my_bookings_page()

    else:
        # AI 馆员聊天（原样不动）
        st.title("❖ AI 馆员在线中")

        # 渲染历史
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                # ⭐ 助手消息若带执行轨迹，挂面板（历史回填的消息无 activity，不显示）
                if msg["role"] == "assistant" and msg.get("activity"):
                    render_activity_panel(msg["activity"])

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
                            data = res.json()
                            ans = data.get("response")
                            # ⭐ 捕获服务端 mint 的 thread_id（新会话首条消息后）
                            st.session_state.thread_id = data.get("thread_id", st.session_state.thread_id)
                            st.markdown(ans)
                            # ⭐ 本轮执行轨迹：即时渲染 + 随消息持久化（跨 rerun）
                            activity = data.get("activity", {})
                            render_activity_panel(activity)
                            st.session_state.messages.append({"role": "assistant", "content": ans, "activity": activity})
                            # 对话可能改变座位/订单 → rerun 让侧边栏订单刷新
                            st.rerun()
                        else:
                            st.error("后端连接失败")
                    except requests.exceptions.RequestException:
                        st.error("网络异常，请确保 API 已启动")

# streamlit run app.py