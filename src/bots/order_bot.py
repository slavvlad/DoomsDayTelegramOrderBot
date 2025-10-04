from __future__ import annotations

import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

log = logging.getLogger(__name__)

# In-memory user state for the main bot
@dataclass
class UserInfo:
    name: str = ""
    reg_numbers: List[str] = field(default_factory=list)
    license_term: str = ""
    payment_status: Optional[str] = None  # "yes" | "no" | None

user_data: Dict[int, UserInfo] = {}

# ---------- Helpers ----------
def split_igg(raw: str) -> List[str]:
    """Split IGG list by comma/space/newline and remove empties."""
    return [s.strip() for s in raw.replace("\n", ",").replace(" ", ",").split(",") if s.strip()]

def md_or_plain(text_md: str, account_info: str) -> dict:
    """Return kwargs for reply_text: prefer Markdown when ACCOUNT_INFO is present."""
    if account_info:
        return {"text": text_md, "parse_mode": "Markdown"}
    return {"text": text_md.replace(f"[форум]({account_info})", "форум")}

# ---------- Handlers ----------
async def cmd_start_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user_data[uid] = UserInfo()
    msg = (
        "Привет! 👋 Добро пожаловать\n"
        "Я помогу вам оформить заказ бота и отправить квитанцию.\n"
        "Пожалуйста, следуйте указаниям.\n\n"
        "Сначала укажите ваш игровой ник."
    )
    if update.message:
        await update.message.reply_text(msg)

async def cb_license_term(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()

    uid = q.from_user.id
    info = user_data.get(uid)
    if not info:
        await q.message.reply_text("Ошибка: данные пользователя не найдены.")
        return

    info.license_term = q.data  # "неделя" | "месяц" | "полгода"
    keyboard = [
        [InlineKeyboardButton("Да", callback_data="yes")],
        [InlineKeyboardButton("Нет", callback_data="no")],
    ]
    await q.message.reply_text("Вы уже оплатили лицензию?", reply_markup=InlineKeyboardMarkup(keyboard))

async def cb_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()

    uid = q.from_user.id
    info = user_data.get(uid)
    if not info:
        await q.message.reply_text("Ошибка: данные пользователя не найдены.")
        return

    info.payment_status = q.data  # "yes" | "no"
    admin_chat_id: str = context.application.bot_data.get("ADMIN_CHAT_ID", "")
    account_info: str = context.application.bot_data.get("ACCOUNT_INFO", "")

    if info.payment_status == "yes":
        await q.message.reply_text("Пожалуйста, прикрепите квитанцию об оплате.")
        return

    reg_numbers_text = ", ".join(info.reg_numbers)
    user = q.from_user
    username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
    caption = (
        f"Новый запрос на приобретение бота от пользователя {username}:\n"
        f"Имя: {info.name}\n"
        f"Регистрационные номера (IGG): {reg_numbers_text}\n"
        f"Срок лицензии: {info.license_term}\n"
        "Оплата не была произведена."
    )
    await context.bot.send_message(chat_id=admin_chat_id, text=caption, parse_mode="Markdown")
    await q.message.reply_text(
        **md_or_plain(
            "Спасибо. Ваш запрос на оформление лицензии был отправлен администрации. "
            f"Если есть вопросы — наш [форум]({account_info})",
            account_info,
        )
    )

async def handle_message_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if uid not in user_data:
        if update.message:
            await update.message.reply_text("Пожалуйста, начните с команды /start.")
        return
    info = user_data[uid]
    admin_chat_id: str = context.application.bot_data.get("ADMIN_CHAT_ID", "")
    account_info: str = context.application.bot_data.get("ACCOUNT_INFO", "")

    # Text flow
    if update.message and update.message.text:
        text = update.message.text.strip()
        if not info.name:
            info.name = text
            await update.message.reply_text(
                f"Спасибо, {info.name}! Теперь отправьте один или несколько регистрационных номеров (IGG). "
                "Если номеров несколько, используйте ',' или пробел для разделения."
            )
            return
        if not info.reg_numbers:
            info.reg_numbers = split_igg(text)
            keyboard = [
                [InlineKeyboardButton("Неделя", callback_data="неделя")],
                [InlineKeyboardButton("Месяц", callback_data="месяц")],
                [InlineKeyboardButton("Полгода", callback_data="полгода")],
            ]
            await update.message.reply_text("Выберите срок лицензии:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        await update.message.reply_text(
            "Вы уже ввели все необходимые данные. Прикрепите квитанцию, если оплата была произведена."
        )
        return

    # Documents/Photos
    if update.message and (update.message.document or update.message.photo):
        if not info.name:
            await update.message.reply_text("Сначала укажите ваш Ник")
            return
        if not info.reg_numbers:
            await update.message.reply_text("Сначала укажите ваши IGG")
            return
        if not info.license_term:
            keyboard = [
                [InlineKeyboardButton("Неделя", callback_data="неделя")],
                [InlineKeyboardButton("Месяц", callback_data="месяц")],
                [InlineKeyboardButton("Полгода", callback_data="полгода")],
            ]
            await update.message.reply_text("Сначала выберите срок лицензии:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if info.payment_status == "yes":
            try:
                if update.message.document:
                    file_id = update.message.document.file_id
                    filename = update.message.document.file_name or "document"
                else:
                    file_id = update.message.photo[-1].file_id
                    filename = "photo.jpg"

                f = await context.bot.get_file(file_id)
                file_bytes = await f.download_as_bytearray()
                stream = BytesIO(file_bytes); stream.seek(0)

                reg_numbers_text = ", ".join(info.reg_numbers)
                user = update.message.from_user
                username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
                caption = (
                    f"Новый запрос на приобретение бота от пользователя {username}:\n"
                    f"Имя: {info.name}\n"
                    f"Регистрационные номера (IGG): {reg_numbers_text}\n"
                    f"Срок лицензии: {info.license_term}\n"
                    "Оплата была произведена."
                )
                await context.bot.send_document(chat_id=admin_chat_id, document=stream, filename=filename, caption=caption)
                await update.message.reply_text(
                    **md_or_plain("Спасибо. Квитанция успешно отправлена администратору! "
                                  f"Если есть вопросы — наш [форум]({account_info})", account_info)
                )
            except Exception as e:
                log.exception("Error while processing receipt")
                await update.message.reply_text(f"Произошла ошибка при обработке файла: {e}")
        else:
            reg_numbers_text = ", ".join(info.reg_numbers)
            user = update.message.from_user
            username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
            caption = (
                f"Новый запрос на приобретение бота от пользователя {username}:\n"
                f"Имя: {info.name}\n"
                f"Регистрационные номера (IGG): {reg_numbers_text}\n"
                f"Срок лицензии: {info.license_term}\n"
                "Оплата не была произведена."
            )
            await context.bot.send_message(chat_id=admin_chat_id, text=caption, parse_mode="Markdown")
            await update.message.reply_text(
                **md_or_plain("Спасибо. Ваш запрос на оформление лицензии был отправлен администрации. "
                              f"Если есть вопросы — наш [форум]({account_info})", account_info)
            )

# ---------- Builder ----------
def build_main_bot(token: str) -> Application:
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start_main))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_main))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_message_main))
    app.add_handler(CallbackQueryHandler(cb_license_term, pattern=r"^(неделя|месяц|полгода)$"))
    app.add_handler(CallbackQueryHandler(cb_payment, pattern=r"^(yes|no)$"))
    return app
