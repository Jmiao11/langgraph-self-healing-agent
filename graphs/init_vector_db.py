#graphs/init_vector_db.py
import os
import dotenv
from pydantic import BaseModel, Field
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain_core.documents import Document

dotenv.load_dotenv()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

# 动态拼接 Docs 目录和 ChromaDB 目录
DOCS_DIR = os.path.join(PROJECT_ROOT, "data", "docs")
DB_PATH = os.path.join(PROJECT_ROOT, "data", "chroma_db")


# ==========================================
# 1. 定义我们想要的元数据结构 (Pydantic Schema)
# ==========================================
class RuleMetadata(BaseModel):
    category: str = Field(description="规则的分类，例如：'预约规则', '违约处罚', '开放时间', '行为规范', '其他'")
    target_audience: str = Field(description="适用人群，例如：'全体读者', '本科生', '研究生', '考研党'")
    involves_penalty: bool = Field(description="该条款是否涉及扣除积分、暂停权限等惩罚措施？(True/False)")
    keywords: list[str] = Field(description="提取3-5个最核心的专业检索关键词")


def build_vector_db_with_auto_metadata():
    print("🚀 启动【梦想自习室】自动化知识库构建 (大模型自动打标版)...")

    # 1. 加载文档并切分 (与之前一样)
    loader = DirectoryLoader(DOCS_DIR, glob="**/*.txt", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"})
    docs = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
    split_docs = text_splitter.split_documents(docs)
    print(f"✂️ 文档已切分为 {len(split_docs)} 个片段。")

    # ==========================================
    # ⭐ 2. 核心改造：调用 LLM 挨个给片段打标签
    # ==========================================
    print("🧠 正在唤醒大模型，开始执行自动化特征提取 (这可能需要一小会儿)...")

    # 实例化大模型 (复用你现有的 Kimi 即可)
    llm = ChatOpenAI(
        api_key=os.environ.get("MOONSHOT_API_KEY"),
        base_url="https://api.moonshot.cn/v1",
        model="kimi-k2-turbo-preview",
        temperature=0,
    )

    # 强制 LLM 输出咱们定义的 RuleMetadata 结构！
    structured_llm = llm.with_structured_output(RuleMetadata)

    rich_docs = []  # 用来存放带标签的新文档

    for i, doc in enumerate(split_docs):
        text = doc.page_content
        print(f"   ⏳ 正在分析第 {i + 1}/{len(split_docs)} 个片段...")

        try:
            # 让大模型阅读这个片段，并提取特征
            prompt = f"请仔细阅读以下图书馆规章制度片段，并准确提取元数据信息：\n{text}"
            extracted_meta = structured_llm.invoke(prompt)

            # 将提取出的数据 (转成字典) 塞进 LangChain Document 的 metadata 属性中
            # 注意：ChromaDB 的 metadata 值只支持 字符串、数字或布尔值，不支持列表
            # 所以我们需要把 keywords 列表转成逗号分隔的字符串
            meta_dict = {
                "category": extracted_meta.category,
                "target_audience": extracted_meta.target_audience,
                "involves_penalty": extracted_meta.involves_penalty,
                "keywords": ", ".join(extracted_meta.keywords)  # 列表转字符串
            }

            # 组装超级加强版文档
            rich_doc = Document(page_content=text, metadata=meta_dict)
            rich_docs.append(rich_doc)

            print(f"      ✅ 提取成功! 分类: {meta_dict['category']} | 涉罚: {meta_dict['involves_penalty']}")

        except Exception as e:
            print(f"      ❌ 第 {i + 1} 个片段提取失败，跳过: {e}")

    # ==========================================
    # 3. 存入 ChromaDB (带入灵魂)
    # ==========================================
    print("\n💾 正在将带有高级标签的文档灌入 ChromaDB...")
    embeddings = OpenAIEmbeddings(
        openai_api_key=os.environ.get("SILICONFLOW_API_KEY"),
        openai_api_base="https://api.siliconflow.cn/v1",
        model="BAAI/bge-m3"
    )

    # 存入带有 metadata 的 rich_docs
    vector_store = Chroma.from_documents(
        documents=rich_docs,
        embedding=embeddings,
        persist_directory=DB_PATH
    )

    print(f"✅ 知识库重构完毕！你的 RAG 系统现在拥有了结构化检索的能力！")


if __name__ == "__main__":
    build_vector_db_with_auto_metadata()