from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

import requests
from flask import Blueprint, jsonify, request
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

log = logging.getLogger(__name__)

# =======================
# Telegram bot handlers
# =======================
async def cmd_start_auction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Аукционный бот запущен.\n"
            "Сюда будут приходить уведомления о новых лотах, подходящих под ваши критерии.\n"
            "Введите /id чтобы получить модификационный номер."
        )

async def cmd_id_auction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            f"Ваш идентификационный номер: <code>{update.effective_chat.id}</code>\n"
            "Используйте его в DoomsdayBot, чтобы получать уведомления",
            parse_mode="HTML",
        )

async def cb_auction_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()
    data = (q.data or "")
    try:
        # format: auction:{yes|no}:{decision_id}
        prefix, action, decision_id = data.split(":", 2)
    except ValueError:
        return
    if prefix != "auction" or action not in ("yes", "no") or not decision_id:
        return

    decisions: Dict[str, Dict[str, Any]] = context.application.bot_data.setdefault("DECISIONS", {})
    rec = decisions.setdefault(decision_id, {"answers": [], "created": time.time()})
    uid = q.from_user.id
    if not any(a.get("user_id") == uid for a in rec["answers"]):
        rec["answers"].append({"user_id": uid, "action": action, "ts": time.time()})

    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    try:
        await q.message.reply_text(
            "Ваш выбор принят: " + ("Купить ✅. Посетите аукцион внутри игры" if action == "yes" else "Не покупать ❌")
        )
    except Exception:
        pass

def build_auction_bot(token: str) -> Application:
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start_auction))
    app.add_handler(CommandHandler("id", cmd_id_auction))
    app.add_handler(CallbackQueryHandler(cb_auction_buy, pattern=r"^auction:(yes|no):"))
    return app


# =======================
# Flask blueprint (HTTP)
# =======================
def create_auction_blueprint(token_auction: str, decisions: Dict[str, Dict[str, Any]]) -> Blueprint:
    """
    Factory that returns a Blueprint with /notify and /decision/<id> endpoints.
    We close over token_auction and decisions to avoid globals/import cycles.
    """
    bp = Blueprint("auction_api", __name__)

    @bp.route("/notify", methods=["POST"])
    def post_notify():
        """
        Accept lot notification and send it to recipients with inline buttons.
        multipart/form-data:
          - photo: binary (PNG/JPG)
          - caption: str
          - decision_id: str
          - chat_ids: comma-separated str, e.g. "751393268,-100123..."
        """
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

        decisions.setdefault(decision_id, {"answers": [], "created": time.time()})

        url = f"https://api.telegram.org/bot{token_auction}/sendPhoto"
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

    @bp.route("/decision/<decision_id>")
    def get_decision(decision_id: str):
        """
        Return consolidated decision for a given decision_id.
        status:
          - "yes" if any user pressed Yes
          - "no"  if at least one No and no Yes
          - "pending" otherwise
        """
        data = decisions.get(decision_id)
        if not data:
            return jsonify({"status": "pending", "answers": []})
        answers = data.get("answers", [])
        has_yes = any(a.get("action") == "yes" for a in answers)
        has_no = any(a.get("action") == "no" for a in answers)
        status = "yes" if has_yes else ("no" if has_no else "pending")
        return jsonify({"status": status, "answers": answers, "created": data.get("created")})

    return bp
