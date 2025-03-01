import os
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Словарь для хранения данных пользователей
user_data = {}

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
ACCOUNT_INFO = os.getenv("ACCOUNT_INFO")

if not TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN and ADMIN_ID must be set in environment variables.")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data[user_id] = {'name': '', 'reg_numbers': [], 'email': ''}  # Добавляем email в словарь

    welcome_message = (
        "Привет! 👋 Добро пожаловать в нашего бота.\n\n"
        "Я помогу вам оформить заказ бота и отправить квитанцию.\n"
        "Пожалуйста, следуйте указаниям.\n\n"
        "Сначала отправьте свой игровой ник."
    )
    await update.message.reply_text(welcome_message)

# Объединенная функция для обработки текстов и файлов
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_data:
        await update.message.reply_text("Пожалуйста, начните с команды /start.")
        return

    # Получаем текущую стадию заполнения данных
    user_info = user_data[user_id]

    # Если пользователь отправил текст
    if update.message.text:
        text = update.message.text

        if not user_info['name']:
            # Заполняем имя и фамилию
            user_info['name'] = text
            await update.message.reply_text(f"Спасибо {user_info['name']}! Теперь отправьте один или несколько регистрационных номеров (IGG). Если номеров несколько, используйте , или пробел для перечисления")
        elif not user_info['reg_numbers']:
            # Заполняем регистрационные номера
            reg_numbers = [num.strip() for num in text.replace('\n', ',').replace(' ', ',').split(',') if num.strip()]
            user_info['reg_numbers'] = reg_numbers
            await update.message.reply_text("Спасибо! Теперь отправьте ваш email на который придет ссылка для скачивания бота")
        elif not user_info['email']:
            # Запрашиваем email
            user_info['email'] = text
            await update.message.reply_text(f"Спасибо! Напишите [мне]({ACCOUNT_INFO}) для получение реквезитов для перевода.Сумма перевода должна соответсвовать стоимости времени лицензии бота указаную в [прайс листе](https://t.me/c/2001621446/3/39) и прикрепите квитанцию о оплате здесь.",
        parse_mode='Markdown')
        else:
            await update.message.reply_text("Вы уже ввели все данные. Пожалуйста, прикрепите файл квитанции.")

    # Если пользователь отправил документ
    elif update.message.document or update.message.photo:
        if not user_info['name'] or not user_info['reg_numbers'] or not user_info['email']:
            await update.message.reply_text("Пожалуйста, сначала отправьте ваше имя, регистрационные номера и email.")
            return

        try:
            # Проверяем тип файла (документ или фото)
            if update.message.document:
                file_id = update.message.document.file_id
                file_name = update.message.document.file_name
            elif update.message.photo:
                file_id = update.message.photo[-1].file_id
                file_name = "photo.jpg"

            file = await context.bot.get_file(file_id)
            file_path = f"./{file_name}"
            await file.download_to_drive(file_path)

            # Подготовка сообщения для отправки админу
            reg_numbers_text = ', '.join(user_info['reg_numbers'])
            user = update.message.from_user
            username = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
            caption = (
                f"Новая квитанция от пользователя {username}:\n"
                f"Имя: {user_info['name']}\n"
                f"Регистрационные номера (IGG): {reg_numbers_text}\n"
                f"Email: {user_info['email']}"
            )

            # Отправляем файл админу
            await context.bot.send_document(chat_id=ADMIN_ID, document=open(file_path, "rb"), caption=caption)
            await update.message.reply_text("Квитанция успешно отправлена админу! Как только лицензия будет готова, вы получите извещение на указаный email.")

        except Exception as e:
            await update.message.reply_text(f"Произошла ошибка при обработке файла: {e}")

        finally:
            # Удаляем временный файл
            if os.path.exists(file_path):
                os.remove(file_path)

    # Если сообщение не содержит текст или файл
    else:
        await update.message.reply_text("Пожалуйста, отправьте текст или прикрепите файл.")

# Команда для получения ID (для настройки ADMIN_ID)
#async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
#    user_id = update.message.from_user.id
#    await update.message.reply_text(f"Ваш Telegram ID: {user_id}")

# Основной код
def main():
    # Создайте приложение Telegram
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start))
    #app.add_handler(CommandHandler("getid", get_my_id))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    #app.add_handler(CallbackQueryHandler(button))  # Обработчик для кнопки Start

    # Запуск бота
    app.run_polling()

if __name__ == "__main__":
    main()
