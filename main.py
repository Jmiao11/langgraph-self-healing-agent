# main
import asyncio
import os

import dotenv
from langchain_core.messages import HumanMessage
import uuid

# 引入我们的工厂组件和业务组件
from infrastructure.dependencies import init_memory_checkpointer, init_vector_store, init_bm25_retriever, init_llm_pool
from services.retrieval_service import RetrievalService
from graphs.router import create_router_app

# 加载环境变量
dotenv.load_dotenv()


# 1. 将普通函数变为异步函数
async def run():
    print("🚀 Booking Agent 工业级重构版已启动 (输入 q 退出)")

    print("⏳ [系统自检] 正在初始化底层存储与检索引擎...")

    # 1. 初始化所有底层设施 (Infrastructure Layer)
    silicon_key = os.environ.get("SILICONFLOW_API_KEY")
    vector_store = init_vector_store(silicon_key)
    bm25_retriever = init_bm25_retriever()
    checkpointer = await init_memory_checkpointer()
    llm_pool = init_llm_pool()  # ⭐ 新增：构造 LLM 池

    # 2. 组装业务服务层 (Service Layer)
    retrieval_service = RetrievalService(vector_store, bm25_retriever)

    # 3. 注入图编排层 (Orchestrator Layer)
    print("⏳ [系统自检] 正在连接 MCP 服务并编译多智能体状态图...")
    router_app = await create_router_app(checkpointer, retrieval_service, llm_pool)  # ⭐ 透传


    # === 替换 ID 生成逻辑 ===
    print("------------------------------------------------")
    user_id_input = input("🔑 请输入历史会话 ID (直接回车则开启全新会话): ").strip()
    if user_id_input:
        thread_id = user_id_input
        print(f"🔄 正在恢复历史记忆，会话 ID: {thread_id}")
    else:
        thread_id = str(uuid.uuid4())
        print(f"🆔 已开启新会话 ID: {thread_id}")
    print("------------------------------------------------")
    print(f"🆔 当前会话 ID: {thread_id}")


    while True:
        try:
            text = input("\n你: ").strip()
            if text.lower() in {"q", "quit", "exit"}:
                print("👋 Bye!")
                await asyncio.sleep(0.1)
                break

            if text.lower() == "new":
                thread_id = str(uuid.uuid4())
                print(f"🔄 已开启新会话: {thread_id}")
                continue

            if not text:
                continue

            init = {
                "messages": [HumanMessage(content=text)],
                "student_id": "stu001",
                "user_name": "沈建大图情测试员",
                "repair_attempts": 0,  # ⭐ 每轮新对话重置自愈计数器
            }

            print(f"🤖 正在思考: {text} ...")

            config = {"configurable": {"thread_id": thread_id}}

            # 使用 stream 模式运行图
            async for ev in router_app.astream(init, stream_mode="updates", config=config):
                # import json
                # # 使用 json.dumps 格式化打印，方便阅读
                # print(json.dumps(ev, indent=2, ensure_ascii=False, default=str))
                for node, payload in ev.items():
                    print(f"node:{node}, payload:{payload}")

                    # 【防御性修复】：确保 payload 是字典，且不为空
                    if payload is None or not isinstance(payload, dict):
                        continue

                    # 打印节点产生的消息
                    if "messages" in payload:
                        m = payload["messages"][-1]
                        msg_type = m.__class__.__name__
                        content = getattr(m, "content", "")
                        tool_calls = getattr(m, "tool_calls", [])

                        print(f"   📍 [{node}] {msg_type}")
                        if content:
                            print(f"       💬 {content}")
                        if tool_calls:
                            print(f"       🛠️ Call: {tool_calls[0]['name']} args={tool_calls[0]['args']}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"❌ 发生错误: {e}")


if __name__ == "__main__":
    # 4. 关键改动：使用 asyncio.run() 启动整个异步程序
    asyncio.run(run())