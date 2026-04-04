import re
from typing import Any

from app.config import settings

try:
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from langchain_openai import OpenAIEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    VECTOR_RAG_AVAILABLE = True
except Exception:
    Chroma = None
    Document = None
    OpenAIEmbeddings = None
    RecursiveCharacterTextSplitter = None
    VECTOR_RAG_AVAILABLE = False

class RAGService:
    """Manages document chunking and vector retrieval for Hierarchical RAG."""
    
    def __init__(self):
        self._vector_enabled = False
        self._fallback_store: dict[str, list[dict[str, Any]]] = {}
        self.vector_store = None
        self.text_splitter = None

        if VECTOR_RAG_AVAILABLE and settings.OPENAI_API_KEY:
            try:
                self.embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)
                # In-memory vector store keeps setup simple for local runs.
                self.vector_store = Chroma(
                    embedding_function=self.embeddings,
                    collection_name="rfp_chunks",
                )
                self.text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1500,
                    chunk_overlap=200,
                    separators=["\n\n", "\n", r"(?<=\. )", " ", ""]
                )
                self._vector_enabled = True
            except Exception:
                self._vector_enabled = False

    @staticmethod
    def _basic_chunks(text: str, chunk_size: int = 1500, overlap: int = 200) -> list[str]:
        clean = (text or "").strip()
        if not clean:
            return []

        chunks: list[str] = []
        step = max(chunk_size - overlap, 1)
        start = 0
        while start < len(clean):
            chunks.append(clean[start:start + chunk_size])
            start += step
        return chunks

    @staticmethod
    def _keyword_score(content: str, query: str) -> int:
        query_tokens = set(re.findall(r"\w+", (query or "").lower()))
        if not query_tokens:
            return 0
        content_tokens = set(re.findall(r"\w+", (content or "").lower()))
        return len(content_tokens.intersection(query_tokens))

    def process_and_store(self, job_id: str, text: str) -> None:
        """Splits the RFP text and stores it in ChromaDB."""
        chunks = (
            self.text_splitter.split_text(text)
            if self._vector_enabled and self.text_splitter
            else self._basic_chunks(text)
        )

        if self._vector_enabled and self.vector_store:
            documents = [
                Document(page_content=chunk, metadata={"job_id": job_id, "chunk_idx": i})
                for i, chunk in enumerate(chunks)
            ]
            if documents:
                self.vector_store.add_documents(documents)
            return

        self._fallback_store[job_id] = [
            {"content": chunk, "metadata": {"job_id": job_id, "chunk_idx": i}}
            for i, chunk in enumerate(chunks)
        ]

    def query(self, job_id: str, query_text: str, k: int = 5) -> list[dict[str, Any]]:
        """Queries the vector DB for chunks relevant to the job_id and query."""
        if self._vector_enabled and self.vector_store:
            try:
                results = self.vector_store.similarity_search(
                    query=query_text,
                    k=k * 3,
                    filter={"job_id": job_id},
                )
                # Post-filter so chunks never leak across jobs if the backend ignores filter.
                filtered = [
                    d for d in results
                    if (d.metadata or {}).get("job_id") == job_id
                ][:k]
                return [{"content": d.page_content, "metadata": d.metadata} for d in filtered]
            except Exception:
                # Fall through to lexical search if vector retrieval fails at runtime.
                pass

        docs = self._fallback_store.get(job_id, [])
        if not docs:
            return []

        scored = [
            (self._keyword_score(d["content"], query_text), d)
            for d in docs
        ]
        ranked = [d for score, d in sorted(scored, key=lambda item: item[0], reverse=True) if score > 0]
        selected = ranked[:k] if ranked else docs[:k]
        return [{"content": d["content"], "metadata": d["metadata"]} for d in selected]

rag_service = RAGService()
