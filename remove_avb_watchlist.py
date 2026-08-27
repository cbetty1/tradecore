import json

path = "config/watchlist_paper.json"
with open(path, "r") as f:
    data = json.load(f)

if isinstance(data, dict):
    for key, val in data.items():
        if isinstance(val, list):
            before = len(val)
            val[:] = [s for s in val if s.get("ticker") != "AVB"]
            after = len(val)
            print(f"Removed {before - after} AVB entr(ies) from '{key}'")
elif isinstance(data, list):
    before = len(data)
    data[:] = [s for s in data if s.get("ticker") != "AVB"]
    after = len(data)
    print(f"Removed {before - after} AVB entr(ies)")

with open(path, "w") as f:
    json.dump(data, f, indent=2)

print("Saved successfully")
