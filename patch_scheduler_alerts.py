import sys

path = "scheduler.py"
with open(path, "r") as f:
    content = f.read()

old = "        for action in actions:\n            if action[\"action\"] == \"BUY\":"
new = "        for action in actions:\n            if action.get(\"paper\"):\n                continue  # MOMENTUM-blocked or otherwise paper-forced — no live alert\n            if action[\"action\"] == \"BUY\":"

count = content.count(old)
print(f"Found {count} matching block(s)")

if count == 0:
    print("ERROR: no matching blocks found — aborting, no changes made")
    sys.exit(1)

content = content.replace(old, new)
with open(path, "w") as f:
    f.write(content)
print(f"Patched {count} block(s) in {path}")
