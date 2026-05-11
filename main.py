import logging
import threading
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


def start_dashboard():
    """Start the Dash dashboard in a background thread."""
    from dashboard.app import app
    logger.info("Dashboard starting at http://localhost:8050")
    app.run(debug=False, host="0.0.0.0", port=8050, use_reloader=False)


def start_scheduler():
    """Start the APScheduler."""
    from scheduler import start
    start()


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("  ⚡ TradeCore Starting")
    logger.info("=" * 50)

    # Start dashboard in background thread
    dashboard_thread = threading.Thread(target=start_dashboard, daemon=True)
    dashboard_thread.start()

    # Send startup notification
    try:
        from notifications.telegram import send_message
        send_message("⚡ <b>TradeCore Started</b>\n\nScheduler running.\nDashboard: http://localhost:8050")
    except Exception as e:
        logger.warning(f"Startup notification failed: {e}")

    # Start scheduler on main thread
    start_scheduler()