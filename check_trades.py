from database.db import get_connection

with get_connection() as conn:
    rows = conn.execute(
        'SELECT ticker, direction, quantity, price, status, opened_at, closed_at FROM trades ORDER BY opened_at DESC LIMIT 15'
    ).fetchall()
    for r in rows:
        print(dict(r))