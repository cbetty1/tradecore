from database.db import get_connection
from datetime import datetime

with get_connection() as conn:
    conn.execute("""
        UPDATE trades 
        SET status = 'CLOSED', 
            closed_at = '2026-05-05 06:04:05'
        WHERE ticker = 'AMD' 
        AND opened_at = '2026-05-02 18:33:06'
        AND status = 'OPEN'
    """)
    conn.commit()
    print("AMD orphan record closed successfully")