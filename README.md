# 梦想自习室 LangGraph Self-Healing Agent

> 🚧 README 完整版正在编写中...

一个基于 LangGraph 构建的、具备**自愈能力**与**多层安全防御**的多智能体系统。

## 项目状态

- ✅ 核心代码完成（详见 `graphs/`、`services/`、`infrastructure/`）
- 🚧 架构图与设计文档编写中
- 🚧 完整 README 重写中

## 快速开始

```bash
# 1. 配置环境变量
cp .env.example .env
# 然后填入你的 API Keys

# 2. 安装依赖
pip install -r requirements.txt   # （requirements.txt 待补充）

# 3. 初始化数据库
python mcp_server/init_db.py
python graphs/init_vector_db.py

# 4. 启动 API 服务
python api.py

# 5. 启动 Streamlit 界面（新开一个终端）
streamlit run app.py
```

## 技术栈

LangGraph · LangChain · MCP · ChromaDB · FastAPI · Streamlit · Moonshot Kimi

## License

MIT