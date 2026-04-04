from app.db import get_db_connection
from typing import List, Optional
from app.rfp_schema import UniversalRFP

def search_rfps(query: str = "", product: str = "") -> List[UniversalRFP]:
    """Retrieve RFPs matching exact product filters and/or full text search queries."""
    results = []
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Build query dynamically
        sql = "SELECT DISTINCT rfps.* FROM rfps"
        params = []
        conditions = []
        
        if query:
            sql += " JOIN rfps_fts ON rfps.rowid = rfps_fts.rowid"
            conditions.append("rfps_fts MATCH ?")
            # Enclose FTS queries in quotes or use wildcard for broad retrieval
            # For simplicity, if they search "pencil", we use "pencil*".
            fts_term = f"{query}*" if "*" not in query else query
            params.append(fts_term)
            
        if product:
            conditions.append("rfps.productName = ?")
            params.append(product)
            
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
            
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        
        for row in rows:
            data = dict(row)
            if data.get("productName") and len(data["productName"]) > 95:
                data["productName"] = data["productName"][:92] + "..."
            results.append(UniversalRFP(**data))
            
    return results
