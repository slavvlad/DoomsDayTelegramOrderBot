# Python 3.10+
# pip install python-telegram-bot==21.6 flask==3.0.3 requests==2.*
# Entrypoint: runs Flask health + two Telegram bots (polling) in one process.

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List

import requests
from flask import Flask, jsonify, request

from bots.order_bot import build_main_bot
from bots.auction_bot import build_auction_bot


DECISIONS: Dict[str, Dict[str, Any]] = {}

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

# ---------- ENV / Config (single source of truth) ----------
TOKEN_MAIN: str | None = os.getenv("BOT_TOKEN") or os.getenv("TG_BOT_TOKEN_MAIN")
TOKEN_AUCTION: str | None = os.getenv("TG_BOT_TOKEN_AUCTION")  # optional
ADMIN_CHAT_ID: str | None = (os.getenv("ADMIN_ID") or "").strip()  # user/group/channel id
ACCOUNT_INFO: str = os.getenv("ACCOUNT_INFO", "")  # optional url for users

if not TOKEN_MAIN or not ADMIN_CHAT_ID:
    raise ValueError("BOT_TOKEN (or TG_BOT_TOKEN_MAIN) and ADMIN_ID must be provided.")

# ---------- Async main ----------
async def amain() -> None:
    # Start Flask in a background thread
    threading.Thread(target=run_server, daemon=True).start()

    # Build apps
    app1 = build_main_bot(TOKEN_MAIN)
    # Provide shared config to handlers via bot_data
    app1.bot_data["ADMIN_CHAT_ID"] = ADMIN_CHAT_ID
    app1.bot_data["ACCOUNT_INFO"] = ACCOUNT_INFO

    app2 = None
    if TOKEN_AUCTION:
        app2 = build_auction_bot(TOKEN_AUCTION)

    # Initialize
    await app1.initialize()
    if app2:
        await app2.initialize()

    # Start
    await app1.start()
    if app2:
        await app2.start()

    # Start polling (no run_polling)
    await app1.updater.start_polling()
    if app2:
        await app2.updater.start_polling()

    try:
        # Keep the process alive
        await asyncio.Event().wait()
    finally:
        # Stop polling
        if app2:
            await app2.updater.stop()
        await app1.updater.stop()

        # Stop apps
        if app2:
            await app2.stop()
            await app2.shutdown()
        await app1.stop()
        await app1.shutdown()

# ---------- HTTP endpoints used by auction component ----------
@flask_app.route("/notify", methods=["POST"])
def post_notify():
    """
    Accepts lot notification from auction component and sends it to recipients with
    inline buttons "Buy Yes/No".

    Expected multipart/form-data fields:
      - photo: binary file (PNG/JPG)
      - caption: str
      - decision_id: str
      - chat_ids: comma-separated str, e.g. "751393268,-100123..."
    """
    if not TOKEN_AUCTION:
        return jsonify({"ok": False, "error": "TG_BOT_TOKEN_AUCTION is empty"}), 400

    file = request.files.get("photo")
    caption = request.form.get("caption", "")
    decision_id = request.form.get("decision_id", "")
    chat_ids_raw = request.form.get("chat_ids", "")

    if not file or not decision_id or not chat_ids_raw:
        return jsonify({"ok": False, "error": "photo/decision_id/chat_ids are required"}), 400

    reply_markup = {
        "inline_keyboard": [[
            {"text": "Купить ✅", "callback_data": f"auction:yes:{decision_id}"},
            {"text": "Нет ❌",    "callback_data": f"auction:no:{decision_id}"},
        ]]
    }

    chat_ids = [s.strip() for s in chat_ids_raw.split(",") if s.strip()]
    if not chat_ids:
        return jsonify({"ok": False, "error": "no recipients"}), 400

    DECISIONS.setdefault(decision_id, {"answers": [], "created": time.time()})

    url = f"https://api.telegram.org/bot{TOKEN_AUCTION}/sendPhoto"
    results: List[Dict[str, Any]] = []

    for cid in chat_ids:
        data = {
            "chat_id": cid,
            "caption": caption,
            "reply_markup": json.dumps(reply_markup, ensure_ascii=False),
        }
        files = {"photo": (file.filename or "lot.png", file.stream, file.mimetype or "image/png")}
        try:
            resp = requests.post(url, data=data, files=files, timeout=12)
            ok = resp.status_code == 200 and resp.json().get("ok") is True
            results.append({"chat_id": cid, "ok": ok, "status_code": resp.status_code, "body": resp.text[:200]})
        except Exception as e:
            log.exception("sendPhoto failed")
            results.append({"chat_id": cid, "ok": False, "error": str(e)})

        try:
            file.stream.seek(0)  # reset stream for next recipient
        except Exception:
            pass

    return jsonify({"ok": True, "results": results})

@flask_app.route("/decision/<decision_id>")
def get_decision(decision_id: str):
    """
    Return consolidated decision for a given decision_id.
    status:
      - "yes" if any user pressed Yes
      - "no"  if at least one No and no Yes
      - "pending" otherwise
    """
    data = DECISIONS.get(decision_id)
    if not data:
        return jsonify({"status": "pending", "answers": []})
    answers = data.get("answers", [])
    has_yes = any(a.get("action") == "yes" for a in answers)
    has_no = any(a.get("action") == "no" for a in answers)
    status = "yes" if has_yes else ("no" if has_no else "pending")
    return jsonify({"status": status, "answers": answers, "created": data.get("created")})

# ---------- Entrypoint ----------
if __name__ == "__main__":
    asyncio.run(amain())
