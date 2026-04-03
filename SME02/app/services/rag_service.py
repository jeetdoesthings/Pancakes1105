import os
import uuid
from typing import List, Dict, Any
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.config import settings

class RAGService:
    """Manages document chunking and vector retrieval for Hierarchical RAG."""
    
    def __init__(self):
        self.embeddings = OpenAIEmbeddings(
            api_key=settings.OPENAI_API_KEY
        )
        # Using an in-memory instance. Since the server runs as a single process, this helps testing.
        # For production across workers, we'd supply persist_directory here.
        self.vector_store = Chroma(
            embedding_function=self.embeddings,
            collection_name="rfp_chunks",
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500,
            chunk_overlap=200,
            separators=["\n\n", "\n", r"(?<=\. )", " ", ""]
        )

    def process_and_store(self, job_id: str, text: str) -> None:
        """Splits the RFP text and stores it in ChromaDB."""
        chunks = self.text_splitter.split_text(text)
        
        # We assign job_id as metadata to ensure agents only query the current RFP
        documents = [
            Document(page_content=chunk, metadata={"job_id": job_id, "chunk_idx": i})
            for i, chunk in enumerate(chunks)
        ]
        if documents:
            # We clear out old documents for this job_id if we want, but job_id is random enough
            self.vector_store.add_documents(documents)

    def query(self, job_id: str, query_text: str, k: int = 5) -> List[Dict[str, Any]]:
        """Queries the vector DB for chunks relevant to the job_id and query."""
        results = self.vector_store.similarity_search(
            query=query_text,
            k=k,
            filter={"job_id": job_id}
            # Langchain's Chroma wrapper supports string literal equality filtering directly
        )
        return [{"content": d.page_content, "metadata": d.metadata} for d in results]

rag_service = RAGService()
