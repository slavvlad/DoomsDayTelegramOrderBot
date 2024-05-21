import os
import tempfile
from telegram import Update, Bot, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler

TOKEN = '6959898325:AAHhxcgFsSMQWCwbVVb0NTI942f_pZDpwzs'
ADMIN_CHAT_ID = '751393268'

ASKING_EMAIL, ASKING_REGISTRATION = range(2)


async def start(update: Update, context: CallbackContext) -> None:
    reply_markup = ReplyKeyboardMarkup(
        [[KeyboardButton("Отправить email")], [KeyboardButton("Отправить регистрационный номер")]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "Привет! Пожалуйста, отправьте мне фотографию квитанции, ваш email и регистрационный номер.",
        reply_markup=reply_markup
    )


async def handle_receipt(update: Update, context: CallbackContext) -> None:
    bot: Bot = context.bot
    receipt_file = await update.message.photo[-1].get_file()

    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        await receipt_file.download_to_drive(tmp_file.name)
        tmp_file_path = tmp_file.name

    try:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text="Пользователь отправил фотографию квитанции.")
        with open(tmp_file_path, 'rb') as file:
            await bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=file)
    finally:
        os.remove(tmp_file_path)


async def ask_email(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Пожалуйста, введите ваш email.")
    return ASKING_EMAIL


async def ask_registration_number(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Пожалуйста, введите ваш регистрационный номер.")
    return ASKING_REGISTRATION


async def handle_email(update: Update, context: CallbackContext) -> int:
    email = update.message.text
    bot: Bot = context.bot

    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Пользователь отправил email: {email}")
    await update.message.reply_text("Спасибо! Ваш email получен.")
    return ConversationHandler.END


async def handle_registration_number(update: Update, context: CallbackContext) -> int:
    registration_number = update.message.text
    bot: Bot = context.bot

    await bot.send_message(chat_id=ADMIN_CHAT_ID,
                           text=f"Пользователь отправил регистрационный номер: {registration_number}")
    await update.message.reply_text("Спасибо! Ваш регистрационный номер получен.")
    return ConversationHandler.END


def main() -> None:
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & filters.Regex('^Отправить email$'), ask_email),
            MessageHandler(filters.TEXT & filters.Regex('^Отправить регистрационный номер$'), ask_registration_number)
        ],
        states={
            ASKING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email)],
            ASKING_REGISTRATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration_number)]
        },
        fallbacks=[]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_receipt))
    application.add_handler(conv_handler)

    application.run_polling()


if __name__ == '__main__':
    main()
