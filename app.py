# app
import sys

import streamlit as st
import requests
import uuid

from streamlit.web import cli as stcli

# 页面基础设置
st.set_page_config(page_title="梦想自习室 AI 馆员", page_icon="📚")

# --- 初始化状态 ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "student_id" not in st.session_state:
    st.session_state.student_id = None
if "user_name" not in st.session_state:
    st.session_state.user_name = None
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- 1. 登录逻辑 ---
if not st.session_state.logged_in:
    st.title("🔐 梦想自习室 - 身份认证")
    st.info("提示：测试账号 stu001 / 密码 123")

    with st.form("login"):
        input_id = st.text_input("学号")
        input_pwd = st.text_input("密码", type="password")
        if st.form_submit_button("登录"):
            try:
                res = requests.post(
                    "http://127.0.0.1:8000/api/login",
                    json={"student_id": input_id, "password": input_pwd}
                )

                if res.status_code == 200:
                    user_data = res.json()
                    st.session_state.logged_in = True
                    st.session_state.student_id = input_id
                    st.session_state.user_name = user_data["name"]
                    st.session_state.token = user_data["token"]  # ⭐ 新增：存 token
                    st.rerun()

                else:
                    st.error("学号或密码错误")
            except requests.exceptions.RequestException:  # ⭐ 核心修复：只捕获网络请求失败的异常
                st.error("后端 API 服务未启动或网络连接失败")

# --- 2. 聊天逻辑 ---
else:
    # 侧边栏：用户信息与退出
    with st.sidebar:
        st.success(f"已登录: {st.session_state.user_name}")
        st.write(f"学号: {st.session_state.student_id}")
        if st.button("退出登录"):
            st.session_state.logged_in = False
            st.session_state.messages = []
            st.rerun()

    st.title("📚 AI 馆员在线中")

    # 渲染历史
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 输入处理
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
                    # ⭐ 新增：加 Authorization header
                    headers = {"Authorization": f"Bearer {st.session_state.token}"}
                    res = requests.post(
                        "http://127.0.0.1:8000/api/chat",
                        json=payload,
                        headers=headers  # ⭐
                    )
                    if res.status_code == 200:
                        ans = res.json().get("response")
                        st.markdown(ans)
                        st.session_state.messages.append({"role": "assistant", "content": ans})
                    else:
                        st.error("后端连接失败")
                except Exception:
                    st.error("网络异常，请确保 API 已启动")


# streamlit run app.py
