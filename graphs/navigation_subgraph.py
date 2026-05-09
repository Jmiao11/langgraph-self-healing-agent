# graphs/navigation_subgraph.py
from typing import Annotated, TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
import os


async def build_navigation_app(llm):
    # 1. 配置 MCP 客户端 (高德地图)
    mcp_config = {
        "amap-maps": {
            "command": "npx",
            "args": ["-y", "@amap/amap-maps-mcp-server"],
            "env": {"AMAP_MAPS_API_KEY": os.environ.get("AMAP_MAPS_API_KEY")},
            "transport": "stdio"
        }
    }


    # 注意：在生产环境或常驻服务中，建议在外部维护 Client 的生命周期
    client = MultiServerMCPClient(mcp_config)
    tools = await client.get_tools()

    default_destination = ""
    # 2. 创建基于高德工具的 React Agent
    # 核心：在给 Navigation Agent 的指令中加入逻辑
    system_message = (
        "你是一个专业的导航专家。\n"
        "1. 如果用户提供了起点和终点，直接规划路线。\n"
        "2. 如果用户问‘怎么去自习室’但没给终点，请使用系统提供的默认地址：梦想小镇(互联网村)杭州市余杭区仓前街道良睦路1399号(邮编:311100)。\n"
        "3. 优先尝试获取用户当前位置作为起点。"
    )

    # 注意：这里需要确保父图的字段能透传进来
    # LangGraph 会自动根据同名原则将 RouterState 里的 default_destination 传给子图
    nav_agent = create_react_agent(llm, tools, prompt=system_message)
    return nav_agent