import os
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, File
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
import threading

# Create a Flask application
flask_app = Flask(__name__)


@flask_app.route('/')
def home():
    return "Бот активен!"


def run_server():
    flask_app.run(host="0.0.0.0", port=8080)


# Dictionary to store user data
user_data = {}

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
ACCOUNT_INFO = os.getenv("ACCOUNT_INFO")

if not TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID должны быть заданы в переменных окружения.")


# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data[user_id] = {'name': '', 'reg_numbers': [], 'license_term': '', 'payment_status': None}

    welcome_message = (
        "Привет! 👋 Добро пожаловать\n"
        "Я помогу вам оформить заказ бота и отправить квитанцию.\n"
        "Пожалуйста, следуйте указаниям.\n\n"
        "Сначала укажите ваш игровой ник."
    )
    await update.message.reply_text(welcome_message)


# Handle license term selection
async def license_term_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    answer = query.data
    await query.answer()

    user_info = user_data.get(user_id)
    if not user_info:
        await query.message.reply_text("Ошибка: данные пользователя не найдены.")
        return

    user_info['license_term'] = answer

    # Ask for payment confirmation
    keyboard = [
        [InlineKeyboardButton("Да", callback_data="yes")],
        [InlineKeyboardButton("Нет", callback_data="no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Вы уже оплатили лицензию?", reply_markup=reply_markup)


# Handle payment response
async def payment_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    answer = query.data
    await query.answer()

    user_info = user_data.get(user_id)
    if not user_info:
        await query.message.reply_text("Ошибка: данные пользователя не найдены.")
        return

    user_info['payment_status'] = answer

    if answer == "yes":
        # Запрос на прикрепление квитанции
        await query.message.reply_text("Пожалуйста, прикрепите квитанцию об оплате.")
    else:
        # Пользователь не оплатил
        reg_numbers_text = ', '.join(user_info['reg_numbers'])
        user = query.from_user
        username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
        caption = (
            f"Новый запрос на приобретение бота от пользователя {username}:\n"
            f"Имя: {user_info['name']}\n"
            f"Регистрационные номера (IGG): {reg_numbers_text}\n"
            f"Срок лицензии: {user_info['license_term']}\n"
            "Оплата не была произведена."
        )

        # Отправляем данные администратору без прикрепленной квитанции
        await context.bot.send_message(chat_id=ADMIN_ID, text=caption, parse_mode="Markdown")
        await query.message.reply_text(
            f"Спасибо. Ваш запрос на оформление лицензии был отправлен администрации. Мы свяжемся с вами в ближайшее время для предоставления реквизитов к оплате.\n"
            f"Если у вас возникли какие-то вопросы, вы можете задать их на нашем [форуме]({ACCOUNT_INFO})",
            parse_mode="Markdown")


# Handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_data:
        await update.message.reply_text("Пожалуйста, начните с команды /start.")
        return

    user_info = user_data[user_id]

    if update.message.text:
        text = update.message.text

        if not user_info['name']:
            user_info['name'] = text
            await update.message.reply_text(
                f"Спасибо, {user_info['name']}! Теперь отправьте один или несколько регистрационных номеров (IGG). Если номеров несколько, используйте ',' или пробел для разделения."
            )
        elif not user_info['reg_numbers']:
            reg_numbers = [num.strip() for num in text.replace('\n', ',').replace(' ', ',').split(',') if num.strip()]
            user_info['reg_numbers'] = reg_numbers
            # Ask for license term selection
            keyboard = [
                [InlineKeyboardButton("Неделя", callback_data="неделя")],
                [InlineKeyboardButton("Месяц", callback_data="месяц")],
                [InlineKeyboardButton("Полгода", callback_data="полгода")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Выберите срок лицензии:", reply_markup=reply_markup)
        #elif not user_info['license_term']:


        else:
            await update.message.reply_text("Вы уже ввели все необходимые данные. Пожалуйста, прикрепите квитанцию если оплата была произведена.")

    elif update.message.document or update.message.photo:  # Обработка прикрепленных документов
        if not user_info['name']:
            await update.message.reply_text("C начала укажите ваш Ник")
            return
        elif not user_info['reg_numbers']:
            await update.message.reply_text("C начала укажите ваши IGG")
            return
        elif not user_info['license_term']:
            await update.message.reply_text("Ошибка: сначала выберите срок лицензии.")
            keyboard = [
                [InlineKeyboardButton("Неделя", callback_data="неделя")],
                [InlineKeyboardButton("Месяц", callback_data="месяц")],
                [InlineKeyboardButton("Полгода", callback_data="полгода")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Выберите срок лицензии:", reply_markup=reply_markup)
            return

        # Проверяем, выбрал ли пользователь оплату
        if user_info.get('payment_status') == 'yes':
            # Скачиваем файл и отправляем его администратору
            try:
                # Проверяем тип файла (документ или фото)
                if update.message.document:
                    file_id = update.message.document.file_id
                    file_name = update.message.document.file_name
                elif update.message.photo:
                    file_id = update.message.photo[-1].file_id
                    file_name = "photo.jpg"
                file = await context.bot.get_file(file_id)
                file_bytes = await file.download_as_bytearray()
                file_stream = BytesIO(file_bytes)
                file_stream.seek(0)

                # Подготовка сообщения для отправки админу
                reg_numbers_text = ', '.join(user_info['reg_numbers'])
                user = update.message.from_user
                username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
                caption = (
                    f"Новый запрос на приобретение бота от пользователя {username}:\n"
                    f"Имя: {user_info['name']}\n"
                    f"Регистрационные номера (IGG): {reg_numbers_text}\n"
                    f"Срок лицензии: {user_info['license_term']}\n"
                    "Оплата была произведена."
                )

                # Отправляем файл админу
                await context.bot.send_document(chat_id=ADMIN_ID, document=file_stream, filename=file_name,
                                                caption=caption)
                await update.message.reply_text(
                    "Спасибо. Квитанция успешно отправлена администратору! В ближайшее время мы свяжемся с вами для оформления лицензии.\n"
                    f"Если у вас возникли какие-то вопросы, вы можете задать их на нашем [форуме]({ACCOUNT_INFO})",
                    parse_mode="Markdown")

            except Exception as e:
                await update.message.reply_text(f"Произошла ошибка при обработке файла: {e}")
        else:
            # Если оплату не выбрали, просто отправляем данные без квитанции
            reg_numbers_text = ', '.join(user_info['reg_numbers'])
            user = update.message.from_user
            username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
            caption = (
                f"Новый запрос на приобретение бота от пользователя {username}:\n"
                f"Имя: {user_info['name']}\n"
                f"Регистрационные номера (IGG): {reg_numbers_text}\n"
                f"Срок лицензии: {user_info['license_term']}\n"
                "Оплата не была произведена."
            )

            await context.bot.send_message(chat_id=ADMIN_ID, text=caption, parse_mode="Markdown")
            await update.message.reply_text(
                f"Спасибо. Ваш запрос на оформление лицензии был отправлен администрации. Мы свяжемся с вами в ближайшее время для предоставления реквизитов к оплате.\n"
                f"Если у вас возникли какие-то вопросы, вы можете задать их на нашем [форуме]({ACCOUNT_INFO})",
                parse_mode="Markdown")


# Main function
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(license_term_response, pattern="^(неделя|месяц|полгода)$"))
    app.add_handler(CallbackQueryHandler(payment_response, pattern="^(yes|no)$"))

    app.run_polling()


# Start the web server in a separate thread
threading.Thread(target=run_server, daemon=True).start()

if __name__ == "__main__":
    main()
