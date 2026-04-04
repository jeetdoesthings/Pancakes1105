"""
Similar RFP Retrieval Engine
=============================
Retrieves historically similar RFPs using a hybrid approach:
  1. FTS5 lexical search (first-pass retrieval by keyword overlap)
  2. ChromaDB semantic similarity (second-pass by embedding distance)
  3. Score merging and deduplication

Design: Uses a SEPARATE ChromaDB collection from the document-chunk RAG store.
"""

import re
from typing import Any

from app.config import settings
from app.db import get_db_connection
from app.rfp_schema import UniversalRFP

try:
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from langchain_openai import OpenAIEmbeddings
    VECTOR_RAG_AVAILABLE = True
except Exception:
    Chroma = None
    Document = None
    OpenAIEmbeddings = None
    VECTOR_RAG_AVAILABLE = False


class RFPSimilarityService:
    """Manages RFP-to-RFP similarity retrieval using FTS5 + ChromaDB."""

    def __init__(self):
        self._vector_enabled = False
        self.vector_store = None

        if VECTOR_RAG_AVAILABLE and settings.OPENAI_API_KEY:
            try:
                embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)
                # SEPARATE collection from document chunks
                self.vector_store = Chroma(
                    embedding_function=embeddings,
                    collection_name="rfp_similarity",
                )
                self._vector_enabled = True
            except Exception:
                self._vector_enabled = False

    # ── FTS5 Retrieval ──────────────────────────────────────────────

    def fts5_search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """
        Keyword-based retrieval using SQLite FTS5.
        Expands query tokens with wildcard suffix matching.
        Returns list of {rfp, score} dicts sorted by token overlap.
        """
        if not query.strip():
            return []

        # Tokenize and build FTS5 OR query
        tokens = re.findall(r"\w+", query.lower())
        if not tokens:
            return []

        # FTS5 OR match across all indexed columns
        fts_terms = " OR ".join([f"{t}*" for t in tokens])
        results = []

        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT rfps.*, rank FROM rfps_fts WHERE rfps_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts_terms, k * 2)  # fetch more to re-rank
                )
                rows = cursor.fetchall()
                for row in rows:
                    rfp_dict = dict(row)
                    # Truncate productName to avoid validation errors
                    if rfp_dict.get("productName") and len(rfp_dict["productName"]) > 95:
                        rfp_dict["productName"] = rfp_dict["productName"][:92] + "..."
                    # Score by token overlap with productName + description
                    text = f"{rfp_dict.get('productName', '')} {rfp_dict.get('description', '')} {rfp_dict.get('title', '')}".lower()
                    score = sum(1 for t in tokens if t in text) / len(tokens)
                    results.append({
                        "rfp": UniversalRFP(**rfp_dict),
                        "fts_score": round(score, 3),
                    })
            except Exception:
                # FTS5 table may not have data yet
                pass

        # Sort by score descending
        results.sort(key=lambda x: x["fts_score"], reverse=True)
        return results[:k]

    # ── ChromaDB Semantic Retrieval ─────────────────────────────────

    def semantic_search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """
        Semantic similarity search using OpenAI embeddings.
        Returns list of {rfp, score} dicts sorted by cosine similarity.
        """
        if not self._vector_enabled or not self.vector_store or not query.strip():
            return []

        try:
            results = self.vector_store.similarity_search_with_score(query, k=k)
            output = []
            for doc, score in results:
                # score is distance (lower = more similar); convert to 0-1 similarity
                similarity = max(0, 1 - score)
                try:
                    rfp = UniversalRFP(**doc.metadata)
                except Exception:
                    continue
                output.append({
                    "rfp": rfp,
                    "semantic_score": round(similarity, 3),
                })
            return output
        except Exception:
            return []

    # ── Hybrid Retrieval ────────────────────────────────────────────

    def find_similar_rfps(self, universal_rfp: UniversalRFP, k: int = 3) -> list[dict[str, Any]]:
        """
        Hybrid retrieval: FTS5 + ChromaDB, merged and deduplicated by rfpId.
        Returns top-k results with combined scores.
        """
        # Build a rich query from the UniversalRFP fields
        query_parts = [
            universal_rfp.productName,
            universal_rfp.category or "",
            universal_rfp.description or "",
            universal_rfp.title,
        ]
        query = " ".join([p for p in query_parts if p]).strip()

        if not query:
            return []

        # Parallel retrieval
        fts_results = self.fts5_search(query, k=k * 2)
        semantic_results = self.semantic_search(query, k=k * 2)

        # Merge by rfpId with weighted scoring
        seen: dict[str, dict[str, Any]] = {}

        for item in fts_results:
            rfp_id = item["rfp"].rfpId
            if rfp_id not in seen:
                seen[rfp_id] = {
                    "rfp": item["rfp"],
                    "fts_score": item["fts_score"],
                    "semantic_score": 0.0,
                }

        for item in semantic_results:
            rfp_id = item["rfp"].rfpId
            if rfp_id in seen:
                seen[rfp_id]["semantic_score"] = item["semantic_score"]
            else:
                seen[rfp_id] = {
                    "rfp": item["rfp"],
                    "fts_score": 0.0,
                    "semantic_score": item["semantic_score"],
                }

        # Combined score: 40% FTS5 + 60% semantic (semantic is more discriminative)
        for rfp_id, entry in seen.items():
            entry["combined_score"] = round(
                0.4 * entry["fts_score"] + 0.6 * entry["semantic_score"], 3
            )

        # Sort and return top-k
        ranked = sorted(seen.values(), key=lambda x: x["combined_score"], reverse=True)
        return ranked[:k]

    # ── Indexing ────────────────────────────────────────────────────

    def index_rfp(self, rfp: UniversalRFP, rfp_text: str = "") -> None:
        """
        Add an RFP to the ChromaDB similarity collection.
        Called when a new RFP is processed so it becomes retrievable later.
        """
        if not self._vector_enabled or not self.vector_store:
            return

        try:
            # Index the full RFP text + structured fields as a single document
            content = f"{rfp.title} {rfp.productName} {rfp.category or ''} {rfp.description or ''} {rfp_text}"
            doc = Document(
                page_content=content.strip(),
                metadata=rfp.model_dump(),
            )
            self.vector_store.add_documents([doc])
        except Exception:
            pass  # Graceful degradation — FTS5 still works


rfp_similarity_service = RFPSimilarityService()
