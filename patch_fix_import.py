path = "execution/order_manager.py"
with open(path, "r") as f:
    content = f.read()

old = '''            from datetime import date as _date
            today_str = str(_date.today())
            with get_connection() as _conn:'''

new = '''            from datetime import date as _date
            from database.db import get_connection
            today_str = str(_date.today())
            with get_connection() as _conn:'''

if old not in content:
    print("ERROR: old block not found — aborting, no changes made")
else:
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched successfully")
