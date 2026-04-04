from langchain_core.tools import tool
from app.services.rag_service import rag_service

def build_document_query_tool(job_id: str):
    @tool
    def document_query_tool(query: str) -> str:
        """Searches the original RFP document for information matching the query.
        Use this to pull specific chunks of text from the source document (e.g. 'budget', 'timeline', 'infrastructure needs').
        """
        results = rag_service.query(job_id=job_id, query_text=query, k=5)
        if not results:
            return "No relevant sections found in the RFP."
        
        formatted_results = []
        for i, res in enumerate(results):
            formatted_results.append(f"--- Chunk {i+1} ---\n{res['content']}\n")
        return "\n".join(formatted_results)
    return document_query_tool
