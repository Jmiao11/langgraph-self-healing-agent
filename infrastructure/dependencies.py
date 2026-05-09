# infrastructure/dependencies.py
import os
import aiosqlite
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_community.retrievers import BM25Retriever
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel


async def init_memory_checkpointer() -> AsyncSqliteSaver:
    """初始化图的异步记忆存储 (Memory Store)"""
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    memory_dir = os.path.join(PROJECT_ROOT, "data", "memory")
    os.makedirs(memory_dir, exist_ok=True)
    memory_db_path = os.path.join(memory_dir, "memory.db")

    conn = await aiosqlite.connect(memory_db_path)
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    return checkpointer


def init_vector_store(silicon_key: str) -> Chroma:
    """初始化向量数据库 (Vector Store)"""
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(PROJECT_ROOT, "data", "chroma_db")

    embeddings = OpenAIEmbeddings(
        openai_api_key=silicon_key,
        openai_api_base="https://api.siliconflow.cn/v1",
        model="BAAI/bge-m3"
    )
    # 如果未来要换 Milvus 或 PGVector，只需要改这里，上层业务完全无感！
    return Chroma(persist_directory=db_path, embedding_function=embeddings)


def init_bm25_retriever() -> BM25Retriever:
    """初始化字面量检索引擎"""
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_path = os.path.join(PROJECT_ROOT, "data", "docs")

    loader = DirectoryLoader(docs_path, glob="**/*.txt", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"})
    raw_docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
    split_docs = text_splitter.split_documents(raw_docs)

    retriever = BM25Retriever.from_documents(split_docs)
    retriever.k = 5
    return retriever


def init_llm_pool() -> dict[str, BaseChatModel]:
    """
    构造按"职责"组织的 LLM 实例池。

    设计原则：
    - 子图通过 pool["fast"] / pool["reasoning"] 等语义键获取实例
    - 不暴露 provider/model_name 等实现细节给上层
    - 未来切换底层模型（如 reasoning 改用 Claude）时，仅修改本函数即可

    当前所有角色都使用 kimi-k2-turbo-preview，但架构上保持分离，
    为未来差异化选型预留扩展点。
    """
    moonshot_key = os.environ.get("MOONSHOT_API_KEY")
    moonshot_base = "https://api.moonshot.cn/v1"

    # 共享配置（避免重复）
    common_kwargs = {
        "api_key": moonshot_key,
        "base_url": moonshot_base,
        "max_retries": 3,
    }

    pool = {
        # 用途：路由分类、安全检测、guardrail 拒答
        # 特征：短输入、明确分类、低延迟敏感
        "fast": ChatOpenAI(
            model="kimi-k2-turbo-preview",
            temperature=0,
            **common_kwargs
        ),
        # 用途：业务对话主控、错误分析、QA 检索 agent
        # 特征：多轮推理、工具调用、上下文敏感
        "reasoning": ChatOpenAI(
            model="kimi-k2-turbo-preview",
            temperature=0.1,
            **common_kwargs
        ),
        # 用途：离线元数据抽取（构建知识库时用）
        # 特征：结构化输出强约束、对一致性要求高
        "extraction": ChatOpenAI(
            model="kimi-k2-turbo-preview",
            temperature=0,
            **common_kwargs
        ),
    }

    print("✅ [Infrastructure] LLM 池已初始化（角色: fast / reasoning / extraction）")
    return pool