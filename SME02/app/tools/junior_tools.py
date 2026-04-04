from langchain_core.tools import tool
from app.services.rag_service import rag_service

MAX_CHUNKS_PER_QUERY = 2
MAX_CHARS_PER_CHUNK = 700
MAX_TOTAL_CHARS = 1800

def build_document_query_tool(job_id: str):
    @tool
    def document_query_tool(query: str) -> str:
        """Searches the original RFP document for information matching the query.
        Use this to pull specific chunks of text from the source document (e.g. 'budget', 'timeline', 'infrastructure needs').
        """
        results = rag_service.query(job_id=job_id, query_text=query, k=MAX_CHUNKS_PER_QUERY)
        if not results:
            return "No relevant sections found in the RFP."
        
        formatted_results = []
        used_chars = 0
        for i, res in enumerate(results):
            content = (res.get("content") or "").strip()
            if len(content) > MAX_CHARS_PER_CHUNK:
                content = content[:MAX_CHARS_PER_CHUNK] + " ...[truncated]"
            if used_chars + len(content) > MAX_TOTAL_CHARS:
                break
            formatted_results.append(f"--- Chunk {i+1} ---\n{content}\n")
            used_chars += len(content)

        if not formatted_results:
            return "No relevant sections found in the RFP."
        return "\n".join(formatted_results)
    return document_query_tool
