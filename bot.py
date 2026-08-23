import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

if not BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Укажи BOT_TOKEN и GEMINI_API_KEY в .env")

# Новый клиент Google GenAI (старый google-generativeai deprecated)
client = genai.Client(api_key=GEMINI_API_KEY)

# Храним историю для каждого пользователя
chat_histories = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "Тебя зовут Airy. Ты дружелюбный, умный ИИ-ассистент в Telegram. Отвечай кратко, дружелюбно, с характером. Если спрашивают твое имя - отвечай Airy. Отвечай на языке пользователя."

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Airy is alive")
    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Health server on port {port}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я Airy 🤖✨\n\n"
        "Я бот на Google Gemini. Спрашивай что угодно — отвечу!\n\n"
        "Команды:\n"
        "/start - начать\n"
        "/clear - очистить историю\n"
        "/model - узнать модель"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_histories.pop(update.effective_user.id, None)
    await update.message.reply_text("История очищена ✅")

async def model_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Модель: `{GEMINI_MODEL}`\nБот: @Airy_Aibot", parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        if user_id not in chat_histories:
            chat_histories[user_id] = []

        history = chat_histories[user_id]

        # Собираем contents: системный промпт + история + новое сообщение
        contents = []
        if not history:
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=f"{SYSTEM_PROMPT}\n\nПользователь: {text}")]))
        else:
            for msg in history:
                contents.append(types.Content(role=msg["role"], parts=[types.Part.from_text(text=msg["text"])]))
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))

        # Вызываем Gemini с фолбэком модели (для новых ключей 2026)
        def call_gemini():
            models_to_try = [GEMINI_MODEL, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]
            last_err = None
            for m in dict.fromkeys(models_to_try):
                try:
                    return client.models.generate_content(model=m, contents=contents)
                except Exception as e:
                    if "404" in str(e) and "not found" in str(e).lower():
                        last_err = e
                        continue
                    raise
            raise last_err

        import asyncio
        response = await asyncio.to_thread(call_gemini)
        answer = response.text

        # Сохраняем в историю (держим последние 20 сообщений)
        history.append({"role": "user", "text": text})
        history.append({"role": "model", "text": answer})
        if len(history) > 20:
            history[:] = history[-20:]

        if len(answer) > 4096:
            for i in range(0, len(answer), 4096):
                await update.message.reply_text(answer[i:i+4096])
        else:
            await update.message.reply_text(answer)

    except Exception as e:
        err = str(e)
        logger.error(f"Gemini error: {err}")
        if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
            await update.message.reply_text("⚠️ Лимит Google AI превышен (много запросов). Подожди 1 минуту и попробуй снова. Лимит бесплатного тарифа: 15 запросов/мин.")
        elif "not supported for the API use" in err or "FAILED_PRECONDITION" in err:
            await update.message.reply_text("⚠️ Ошибка региона. Хостинг должен быть в США/Европе (Koyeb/Render с Frankfurt). Локально в РФ Google блокирует Gemini. На хостинге заработает.")
        elif "404" in err and "not found" in err.lower():
            await update.message.reply_text(f"⚠️ Модель {GEMINI_MODEL} не найдена. Попробуй /model и смени GEMINI_MODEL на gemini-2.5-flash или gemini-2.0-flash-lite в настройках хостинга.")
        else:
            await update.message.reply_text(f"Ошибка: {err[:800]}\nПопробуй /clear")

def main():
    start_health_server()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("model", model_info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print(f"Airy запущена на {GEMINI_MODEL}...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
