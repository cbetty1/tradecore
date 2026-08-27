path = "execution/order_manager.py"
with open(path, "r") as f:
    content = f.read()

old = '''        if not final_signal.is_actionable(DEFAULT_CONFIDENCE_THRESHOLD):
            continue'''

new = '''        min_conf_threshold = limits.get("min_confidence_threshold", 65.0)
        if not final_signal.is_actionable(min_conf_threshold):
            logger.info(f"{ticker} — confidence {final_signal.confidence:.1f}% below threshold {min_conf_threshold}%, skipping")
            continue'''

if old not in content:
    print("ERROR: old block not found — aborting, no changes made")
else:
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched successfully")
