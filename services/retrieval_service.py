# services/retrieval_service.py
from langchain_core.documents import Document

class RetrievalService:
    def __init__(self, vector_store, bm25_retriever):
        """
        ⭐ 核心：依赖注入！
        我不在乎你传给我的是 Chroma、Pinecone 还是 Elasticsearch。
        只要 vector_store 实现了 LangChain 的标准检索接口就行。
        """
        self.vector_store = vector_store
        self.bm25_retriever = bm25_retriever
        print("✅ [Service] 接收到注入的双路检索引擎！")

    def _rrf_fuse(self, bm25_docs: list[Document], vector_docs: list[Document], k: int = 60, top_n: int = 3) -> list[
        Document]:
        """内部核心算法：RRF 融合打分"""
        fused_scores = {}

        def process_docs(docs, weight=1.0):
            for rank, doc in enumerate(docs):
                doc_key = hash(doc.page_content)  # 提示：这里你可以换成 hashlib.md5
                if doc_key not in fused_scores:
                    fused_scores[doc_key] = {"doc": doc, "score": 0.0}
                fused_scores[doc_key]["score"] += weight * (1 / (rank + 1 + k))

        process_docs(bm25_docs, weight=1.2)
        process_docs(vector_docs, weight=1.0)

        sorted_items = sorted(fused_scores.values(), key=lambda x: x["score"], reverse=True)
        return [item["doc"] for item in sorted_items[:top_n]]

    def search_rules(self, query: str, category: str = None) -> str:
        """对外暴露的唯一接口：根据 Query 返回融合后的文本串"""
        if not self.vector_store or not self.bm25_retriever:
            return "知识库未初始化，无法查询。"

        print(f"\n🔍 [Service RRF Engine] 收到查询: '{query}', 约束分类: {category}")

        # 两路并发召回
        # 1. 向量检索：如果大模型传了分类，我们就加上精准过滤！
        filter_dict = {"category": category} if category else None
        vec_results = self.vector_store.similarity_search(query, k=5, filter=filter_dict)

        bm25_results = self.bm25_retriever.invoke(query)

        # RRF 融合
        fused_docs = self._rrf_fuse(bm25_results, vec_results, top_n=3)

        if not fused_docs:
            return "未在规章制度中检索到相关内容。"

        for i, d in enumerate(fused_docs):
            print(f"  -> 🏆 RRF 排序第 {i + 1} 名: {d.page_content[:40].replace(chr(10), ' ')}...")

        return "\n\n".join([f"【规章条例片段】：\n{doc.page_content}" for doc in fused_docs])