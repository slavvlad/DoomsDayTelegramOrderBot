# Python 3.10+
# pip install python-telegram-bot==21.6 flask==3.0.3
# Два Telegram-бота в одном процессе (polling) + Flask health на порту 8080.
# Используется initialize/start/updater.start_polling (без run_polling).
import json
import os
import asyncio
import logging
import threading
from io import BytesIO
import time

import requests
from flask import Flask, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO
)
log = logging.getLogger("dual-bots")

# ---------- Flask health ----------
flask_app = Flask(__name__)

DECISIONS = {}  # decision_id -> {"answers": [{"user_id": int, "action": "yes"|"no", "ts": float}], "created": float}

@flask_app.route("/")
def home():
    return "Бот активен!"

def run_server():
    flask_app.run(host="0.0.0.0", port=8080)

# ---------- ENV / Config ----------
# Бот №1 — «заказы/квитанции»
TOKEN_MAIN   = os.getenv("BOT_TOKEN") or os.getenv("TG_BOT_TOKEN_MAIN")
ADMIN_ID     = os.getenv("ADMIN_ID")
ACCOUNT_INFO = os.getenv("ACCOUNT_INFO", "")

# Бот №2 — «аукционный» (если не задан — второй бот не стартует)
TOKEN_AUCTION = os.getenv("TG_BOT_TOKEN_AUCTION")

if not TOKEN_MAIN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN (или TG_BOT_TOKEN_MAIN) и ADMIN_ID должны быть заданы в переменных окружения.")

# ---------- In-memory хранилище для бота №1 ----------
user_data: dict[int, dict] = {}  # { user_id: { name, reg_numbers, license_term, payment_status } }

# ---------- Handlers для бота №1 (текущий бот) ----------
async def cmd_start_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id] = {'name': '', 'reg_numbers': [], 'license_term': '', 'payment_status': None}
    welcome_message = (
        "Привет! 👋 Добро пожаловать\n"
        "Я помогу вам оформить заказ бота и отправить квитанцию.\n"
        "Пожалуйста, следуйте указаниям.\n\n"
        "Сначала укажите ваш игровой ник."
    )
    await update.message.reply_text(welcome_message)

async def cb_license_term(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    answer = query.data
    await query.answer()

    info = user_data.get(user_id)
    if not info:
        await query.message.reply_text("Ошибка: данные пользователя не найдены.")
        return

    info['license_term'] = answer
    keyboard = [
        [InlineKeyboardButton("Да", callback_data="yes")],
        [InlineKeyboardButton("Нет", callback_data="no")],
    ]
    await query.message.reply_text("Вы уже оплатили лицензию?", reply_markup=InlineKeyboardMarkup(keyboard))

async def cb_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    answer = query.data
    await query.answer()

    info = user_data.get(user_id)
    if not info:
        await query.message.reply_text("Ошибка: данные пользователя не найдены.")
        return

    info['payment_status'] = answer

    if answer == "yes":
        await query.message.reply_text("Пожалуйста, прикрепите квитанцию об оплате.")
    else:
        reg_numbers_text = ', '.join(info['reg_numbers'])
        user = query.from_user
        username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
        caption = (
            f"Новый запрос на приобретение бота от пользователя {username}:\n"
            f"Имя: {info['name']}\n"
            f"Регистрационные номера (IGG): {reg_numbers_text}\n"
            f"Срок лицензии: {info['license_term']}\n"
            "Оплата не была произведена."
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=caption, parse_mode="Markdown")
        await query.message.reply_text(
            "Спасибо. Ваш запрос на оформление лицензии был отправлен администрации. "
            f"Мы свяжемся с вами в ближайшее время. Если есть вопросы — наш [форум]({ACCOUNT_INFO})",
            parse_mode="Markdown"
        )

async def handle_message_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data:
        if update.message:
            await update.message.reply_text("Пожалуйста, начните с команды /start.")
        return

    info = user_data[user_id]

    # --- Текстовый сценарий ---
    if update.message and update.message.text:
        text = update.message.text
        if not info['name']:
            info['name'] = text
            await update.message.reply_text(
                f"Спасибо, {info['name']}! Теперь отправьте один или несколько регистрационных номеров (IGG). "
                "Если номеров несколько, используйте ',' или пробел для разделения."
            )
        elif not info['reg_numbers']:
            reg_numbers = [num.strip() for num in text.replace('\n', ',').replace(' ', ',').split(',') if num.strip()]
            info['reg_numbers'] = reg_numbers
            keyboard = [
                [InlineKeyboardButton("Неделя", callback_data="неделя")],
                [InlineKeyboardButton("Месяц", callback_data="месяц")],
                [InlineKeyboardButton("Полгода", callback_data="полгода")],
            ]
            await update.message.reply_text("Выберите срок лицензии:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(
                "Вы уже ввели все необходимые данные. Прикрепите квитанцию, если оплата была произведена."
            )
        return

    # --- Документы/фото ---
    if update.message and (update.message.document or update.message.photo):
        if not info['name']:
            await update.message.reply_text("Сначала укажите ваш Ник")
            return
        if not info['reg_numbers']:
            await update.message.reply_text("Сначала укажите ваши IGG")
            return
        if not info['license_term']:
            keyboard = [
                [InlineKeyboardButton("Неделя", callback_data="неделя")],
                [InlineKeyboardButton("Месяц", callback_data="месяц")],
                [InlineKeyboardButton("Полгода", callback_data="полгода")],
            ]
            await update.message.reply_text("Сначала выберите срок лицензии:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if info.get('payment_status') == 'yes':
            try:
                if update.message.document:
                    file_id = update.message.document.file_id
                    file_name = update.message.document.file_name
                else:
                    file_id = update.message.photo[-1].file_id
                    file_name = "photo.jpg"

                f = await context.bot.get_file(file_id)
                file_bytes = await f.download_as_bytearray()
                stream = BytesIO(file_bytes); stream.seek(0)

                reg_numbers_text = ', '.join(info['reg_numbers'])
                user = update.message.from_user
                username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
                caption = (
                    f"Новый запрос на приобретение бота от пользователя {username}:\n"
                    f"Имя: {info['name']}\n"
                    f"Регистрационные номера (IGG): {reg_numbers_text}\n"
                    f"Срок лицензии: {info['license_term']}\n"
                    "Оплата была произведена."
                )

                await context.bot.send_document(chat_id=ADMIN_ID, document=stream, filename=file_name, caption=caption)
                await update.message.reply_text(
                    "Спасибо. Квитанция успешно отправлена администратору! "
                    f"Если есть вопросы — наш [форум]({ACCOUNT_INFO})", parse_mode="Markdown"
                )
            except Exception as e:
                await update.message.reply_text(f"Произошла ошибка при обработке файла: {e}")
        else:
            reg_numbers_text = ', '.join(info['reg_numbers'])
            user = update.message.from_user
            username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
            caption = (
                f"Новый запрос на приобретение бота от пользователя {username}:\n"
                f"Имя: {info['name']}\n"
                f"Регистрационные номера (IGG): {reg_numbers_text}\n"
                f"Срок лицензии: {info['license_term']}\n"
                "Оплата не была произведена."
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=caption, parse_mode="Markdown")
            await update.message.reply_text(
                "Спасибо. Ваш запрос на оформление лицензии был отправлен администрации. "
                f"Если есть вопросы — наш [форум]({ACCOUNT_INFO})", parse_mode="Markdown"
            )

# ---------- Handlers для бота №2 (аукционный) ----------
async def cmd_start_auction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Аукционный бот запущен.\nСюда будут приходить уведомления о новых лотах подходящих под ваши критерии\nВведите /id чтобы получить модификационный номер"
    )

async def cmd_id_auction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Правка: используем HTML вместо Markdown, чтобы избежать ошибок парсинга
    await update.message.reply_text(
        f"Ваш идентификационный номер: <code>{update.effective_chat.id}</code>\nИспользуйте его в DoomsdayBot, чтобы получать уведомления",
        parse_mode="HTML"
    )

async def cb_auction_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = (q.data or "")
    try:
        prefix, action, decision_id = data.split(":", 3)
    except ValueError:
        return
    if prefix != "auction" or action not in ("yes", "no"):
        return

    rec = DECISIONS.setdefault(decision_id, {"answers": [], "created": time.time()})
    uid = q.from_user.id
    if not any(a.get("user_id") == uid for a in rec["answers"]):
        rec["answers"].append({"user_id": uid, "action": action, "ts": time.time()})

    # снять клавиатуру у исходного сообщения
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    # необязательное подтверждение в чат
    try:
        await q.message.reply_text("Ваш выбор принят: " + ("Купить ✅. Посетите аукцион внутри игры" if action == "yes" else "Не покупать ❌"))
    except Exception:
        pass



# ---------- Builders ----------
def build_main_bot() -> Application:
    app = ApplicationBuilder().token(TOKEN_MAIN).build()
    app.add_handler(CommandHandler("start", cmd_start_main))
    app.add_handler(MessageHandler(filters.ALL, handle_message_main))
    app.add_handler(CallbackQueryHandler(cb_license_term, pattern=r"^(неделя|месяц|полгода)$"))
    app.add_handler(CallbackQueryHandler(cb_payment,      pattern=r"^(yes|no)$"))
    return app

def build_auction_bot() -> Application | None:
    if not TOKEN_AUCTION:
        log.info("TG_BOT_TOKEN_AUCTION не задан — второй бот не будет запущен (это ок).")
        return None
    app = ApplicationBuilder().token(TOKEN_AUCTION).build()
    app.add_handler(CommandHandler("start", cmd_start_auction))
    app.add_handler(CommandHandler("id", cmd_id_auction))
    app.add_handler(CallbackQueryHandler(cb_auction_buy, pattern=r"^auction:(yes|no):"))
    return app

# ---------- Main (асинхронный, без run_polling) ----------
async def amain():
    # Flask health — отдельный поток
    threading.Thread(target=run_server, daemon=True).start()

    app1 = build_main_bot()
    app2 = build_auction_bot()

    # Инициализация
    await app1.initialize()
    if app2:
        await app2.initialize()

    # Старт приложений
    await app1.start()
    if app2:
        await app2.start()

    # Старт polling (НЕ run_polling)
    await app1.updater.start_polling()
    if app2:
        await app2.updater.start_polling()

    # Держим процесс «живым»
    try:
        await asyncio.Event().wait()
    finally:
        # Остановка polling
        if app2:
            await app2.updater.stop()
        await app1.updater.stop()

        # Остановка приложений
        if app2:
            await app2.stop()
            await app2.shutdown()
        await app1.stop()
        await app1.shutdown()


@flask_app.route("/notify", methods=["POST"])
def post_notify():
    """
    Accept lot notification from auction component and send it to recipients
    with inline buttons "Buy Yes/No".
    Expect form-data:
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

    # подготовим клавиатуру
    reply_markup = {
        "inline_keyboard": [[
            {"text": "Купить ✅", "callback_data": f"auction:yes:{decision_id}"},
            {"text": "Нет ❌",    "callback_data": f"auction:no:{decision_id}"},
        ]]
    }

    # нормализуем список получателей
    chat_ids = [s.strip() for s in chat_ids_raw.split(",") if s.strip()]
    if not chat_ids:
        return jsonify({"ok": False, "error": "no recipients"}), 400

    # заранее подготовим запись о решении
    DECISIONS.setdefault(decision_id, {"answers": [], "created": time.time()})

    # отправка
    url = f"https://api.telegram.org/bot{TOKEN_AUCTION}/sendPhoto"
    results = []
    for cid in chat_ids:
        data = {
            "chat_id": cid,
            "caption": caption,
            "reply_markup": json.dumps(reply_markup, ensure_ascii=False),
        }
        files = {"photo": (file.filename or "lot.png", file.stream, file.mimetype or "image/png")}
        try:
            resp = requests.post(url, data=data, files=files, timeout=12)
            ok = (resp.status_code == 200 and resp.json().get("ok") is True)
            results.append({"chat_id": cid, "ok": ok, "status_code": resp.status_code, "body": resp.text[:200]})
        except Exception as e:
            results.append({"chat_id": cid, "ok": False, "error": str(e)})

        # перемотать стрим назад для повторной отправки (важно для нескольких получателей)
        try:
            file.stream.seek(0)
        except Exception:
            pass

    return jsonify({"ok": True, "results": results})


@flask_app.route("/decision/<decision_id>")
def get_decision(decision_id):
    """
    Return consolidated decision for a given decision_id.
    status = "yes" if any user pressed Yes
           = "no"  if there are only No's (at least one) and no Yes
           = "pending" otherwise
    """
    data = DECISIONS.get(decision_id)
    if not data:
        return jsonify({"status": "pending", "answers": []})
    answers = data.get("answers", [])
    has_yes = any(a.get("action") == "yes" for a in answers)
    has_no  = any(a.get("action") == "no"  for a in answers)
    if has_yes:
        status = "yes"
    elif has_no:
        status = "no"
    else:
        status = "pending"
    return jsonify({"status": status, "answers": answers, "created": data.get("created")})

if __name__ == "__main__":
    asyncio.run(amain())
