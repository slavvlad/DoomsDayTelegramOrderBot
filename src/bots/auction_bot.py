from __future__ import annotations

import logging
import time
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)


log = logging.getLogger(__name__)

# ---------- Handlers ----------
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
        # Format: auction:{yes|no}:{decision_id}
        prefix, action, decision_id = data.split(":", 2)
    except ValueError:
        return
    if prefix != "auction" or action not in ("yes", "no") or not decision_id:
        return

    rec = DECISIONS.setdefault(decision_id, {"answers": [], "created": time.time()})
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

# ---------- Builder ----------
def build_auction_bot(token: str) -> Application:
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start_auction))
    app.add_handler(CommandHandler("id", cmd_id_auction))
    app.add_handler(CallbackQueryHandler(cb_auction_buy, pattern=r"^auction:(yes|no):"))
    return app
