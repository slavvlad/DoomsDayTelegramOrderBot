from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Dict

from flask import Flask

from bots.order_bot import build_main_bot
from bots.auction_bot import build_auction_bot, create_auction_blueprint

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("dual-bots")

# ---------- Flask ----------
flask_app = Flask(__name__)

@flask_app.route("/")
@flask_app.route("/health")
def health() -> str:
    return "Bot is alive!"

def run_server() -> None:
    flask_app.run(host="0.0.0.0", port=8080)

# ---------- ENV / Config ----------
TOKEN_MAIN: str | None    = os.getenv("BOT_TOKEN") or os.getenv("TG_BOT_TOKEN_MAIN")
TOKEN_AUCTION: str | None = os.getenv("TG_BOT_TOKEN_AUCTION")  # optional second bot

ADMIN_CHAT_ID: str | None = (os.getenv("ADMIN_ID") or "").strip()
ACCOUNT_INFO: str = os.getenv("ACCOUNT_INFO", "")

if not TOKEN_MAIN or not ADMIN_CHAT_ID:
    raise ValueError("BOT_TOKEN (or TG_BOT_TOKEN_MAIN) and ADMIN_ID must be provided.")

# Shared in-memory store for auction decisions
DECISIONS: Dict[str, Dict[str, Any]] = {}

# Register auction HTTP API (blueprint) if auction token is present
if TOKEN_AUCTION:
    bp = create_auction_blueprint(TOKEN_AUCTION, DECISIONS)
    flask_app.register_blueprint(bp)  # routes: /notify, /decision/<id>

# ---------- Async main ----------
async def amain() -> None:
    # Start Flask in background
    threading.Thread(target=run_server, daemon=True).start()

    # Build main bot
    app1 = build_main_bot(TOKEN_MAIN)
    app1.bot_data["ADMIN_CHAT_ID"] = ADMIN_CHAT_ID
    app1.bot_data["ACCOUNT_INFO"] = ACCOUNT_INFO

    # Build auction bot (optional)
    app2 = None
    if TOKEN_AUCTION:
        app2 = build_auction_bot(TOKEN_AUCTION)
        # share decisions dict with auction bot handlers
        app2.bot_data["DECISIONS"] = DECISIONS

    # Init
    await app1.initialize()
    if app2:
        await app2.initialize()

    # Start
    await app1.start()
    if app2:
        await app2.start()

    # Polling (no run_polling)
    await app1.updater.start_polling()
    if app2:
        await app2.updater.start_polling()

    try:
        await asyncio.Event().wait()
    finally:
        if app2:
            await app2.updater.stop()
        await app1.updater.stop()
        if app2:
            await app2.stop(); await app2.shutdown()
        await app1.stop(); await app1.shutdown()

if __name__ == "__main__":
    asyncio.run(amain())
