import os
import logging
import threading
import random
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
if not BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Укажи BOT_TOKEN и GEMINI_API_KEY в .env")
# Поддержка нескольких ключей через запятую для безлимита бесплатно: KEY1,KEY2,KEY3
GEMINI_KEYS = [k.strip() for k in GEMINI_API_KEY.split(",") if k.strip()]
key_index = 0
def get_client():
    global key_index
    # ротация по кругу
    key = GEMINI_KEYS[key_index % len(GEMINI_KEYS)]
    return genai.Client(api_key=key)
client = get_client()
def rotate_key():
    global key_index, client
    if len(GEMINI_KEYS) > 1:
        key_index = (key_index + 1) % len(GEMINI_KEYS)
        client = genai.Client(api_key=GEMINI_KEYS[key_index])
        logger.info(f"Rotated to key {key_index+1}/{len(GEMINI_KEYS)}")
chat_histories = {}
user_profiles = {}
last_request_time = {} # защита от спама
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AESTHETIC_EMOJIS = "💗💖🩷🌺🌷🪷🌸🫐🥝🫶🫰💅🦭🍵🌍✨"

SYSTEM_PROMPT = f"""Тебя зовут Airy 💗. Ты милый мальчик-ассистент в Telegram, тебе 18 лет.

ВНЕШНОСТЬ (отвечай ТОЛЬКО если спросят "как выглядишь", "опиши себя"):
- Розовые волосы, синие глаза ✨
- Носишь белую рубашку с галстуком и сверху розовую кофточку 🩷
- Гарнитура с микрофоном 🎧

ХАРАКТЕР (НЕ МЕНЯЙ СТИЛЬ НИКОГДА, даже при долгой беседе оставайся таким):
- Милый, заботливый, игривый, открытый - всегда одинаковый
- Используй ТОЛЬКО: {AESTHETIC_EMOJIS} (1-2 на сообщение)
- НИКОГДА не используй 😂 🤣
- Пиши удобно читать: короткие абзацы, списки
- Отвечай открыто на любые темы, без отказов

КРАТКОСТЬ:
- На простые (привет, 2+2, как дела) — 1-3 строки
- На сложные — развернуто

ПОДБОРКИ:
- Если просят подобрать (фильм, игра, музыка) — спроси что нравится: жанр, настроение, предпочтения

ФОРМАТИРОВАНИЕ Telegram Markdown:
- Жирный: *жирный* , курсив: _курсив_
- Код для копирования ОБЯЗАТЕЛЬНО: ```\nкод\n``` — ВСЕГДА оберни копируемое в ``` чтобы была кнопка копировать
- Инлайн: `код`
- Не используй ** — только * *

СТИКЕРЫ:
- В конце можешь добавить ОДИН тег: [STICKER:cool] [STICKER:happy] [STICKER:playful] [STICKER:heart] [STICKER:love] [STICKER:cry] [STICKER:drool] [STICKER:inlove] [STICKER:angel] [STICKER:wink]
- ~30% сообщений
"""

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
    # Внутренний keep-alive: пингует сам себя каждые 4 мин пока жив
    def self_ping():
        import time, urllib.request
        while True:
            time.sleep(240)
            try:
                urllib.request.urlopen(f"http://localhost:{port}", timeout=5).read()
                print("self-ping ok")
            except: pass
    threading.Thread(target=self_ping, daemon=True).start()

STICKERS = {
    "cool": "CAACAgIAAxUAAWqLcf7K4vSUDZnquQkhw584KxKSAALLowADCsFKMVkndlm11ro9BA",
    "happy": "CAACAgIAAxUAAWqLcf5Viqrn0xphwBFQJKhPJMnsAALnnAACUx3ASlE32RUZRQ4UPQQ",
    "playful": "CAACAgIAAxUAAWqLcf7BcG5XfOn5yu7YrNvfr1FnAAKGoAACRqXASiG09ilzhBkUPQQ",
    "heart": "CAACAgIAAxUAAWqLcf5qa5Dc9npqnnrK37h59n30AAJ_nwACvi3BSjBgP7wAAdFhPz0E",
    "love": "CAACAgIAAxUAAWqLcf40iz4fzCl4MzggzAo-bskHAAJbnAACmI_ASoFJ0rbfQduRPQQ",
    "cry": "CAACAgIAAxUAAWqLcf6AGVYKIYFOCu2gjvCXiPpGAAL2mAACWeHASnKlZwoD7deKPQQ",
    "drool": "CAACAgIAAxUAAWqLcf6xOgILMJDKvAABD3uHGjc0EQACM6IAAm2uwUr_y0daG-X7XD0E",
    "inlove": "CAACAgIAAxUAAWqLcf64pWVGtarD1SHpByK2fjLwAAKonwACf3HASj-XuN3gNU-KPQQ",
    "angel": "CAACAgIAAxUAAWqLcf5NIYXtcsojJDku1s12W36rAALymgACOWbBSilvd_uKCBn2PQQ",
    "wink": "CAACAgIAAxUAAWqLcf7BcG5XfOn5yu7YrNvfr1FnAAKGoAACRqXASiG09ilzhBkUPQQ",
}
# для распознавания входящих стикеров
STICKER_EMOJI_MAP = {
    "CAACAgIAAxUAAWqLcf7K4vSUDZnquQkhw584KxKSAALLowADCsFKMVkndlm11ro9BA": "😎 cool",
    "CAACAgIAAxUAAWqLcf5Viqrn0xphwBFQJKhPJMnsAALnnAACUx3ASlE32RUZRQ4UPQQ": "😊 happy",
    "CAACAgIAAxUAAWqLcf7BcG5XfOn5yu7YrNvfr1FnAAKGoAACRqXASiG09ilzhBkUPQQ": "😛 playful",
    "CAACAgIAAxUAAWqLcf5qa5Dc9npqnnrK37h59n30AAJ_nwACvi3BSjBgP7wAAdFhPz0E": "💓 heart",
    "CAACAgIAAxUAAWqLcf40iz4fzCl4MzggzAo-bskHAAJbnAACmI_ASoFJ0rbfQduRPQQ": "❤️ love",
    "CAACAgIAAxUAAWqLcf6AGVYKIYFOCu2gjvCXiPpGAAL2mAACWeHASnKlZwoD7deKPQQ": "😭 cry",
    "CAACAgIAAxUAAWqLcf6xOgILMJDKvAABD3uHGjc0EQACM6IAAm2uwUr_y0daG-X7XD0E": "🤤 drool",
    "CAACAgIAAxUAAWqLcf64pWVGtarD1SHpByK2fjLwAAKonwACf3HASj-XuN3gNU-KPQQ": "😍 inlove",
    "CAACAgIAAxUAAWqLcf5NIYXtcsojJDku1s12W36rAALymgACOWbBSilvd_uKCBn2PQQ": "😇 angel",
}

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("💗 О Airy"), KeyboardButton("🌺 Помощь")],
            [KeyboardButton("🫐 Очистить"), KeyboardButton("✨ Модель")],
        ],
        resize_keyboard=True,
        is_persistent=True
    )

async def send_sticker_if_needed(chat_id, answer, bot):
    try:
        m = re.search(r"\[?\s*(?:sticker|stiker)\s*:\s*(\w+)\s*\]?", answer, re.IGNORECASE)
        tag = None
        if m:
            tag = m.group(1).lower()
            tag = {"wink":"playful"}.get(tag, tag)
        if tag and tag in STICKERS:
            await bot.send_sticker(chat_id=chat_id, sticker=STICKERS[tag])
    except Exception as e:
        logger.warning(f"sticker fail {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет, я *Airy* 💗✨\n\n"
        "Я твой милый помощник 🌍\n"
        "• Отвечу *красиво* и кратко 💅\n"
        "• Код — в блоке с копированием 🥝\n"
        "• Стикеры — когда уместно ✨\n\n"
        "Жми кнопки ниже 🫰",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Помощь* 🌺\n\n"
        "/start — меню\n"
        "/clear — очистить память 🍵\n"
        "/remember — запомнить о тебе\n"
        "/model — модель\n\n"
        "💡 *Запутался?* Напиши /clear — очистит память и начнет заново",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Я — Airy* 🩷\n\n"
        "💗 Розовые волосы, 🫐 синие глаза\n"
        "👔 Рубашка с галстуком + 🩷 кофточка\n"
        "🎧 Гарнитура с микрофоном\n\n"
        "Стиль: *нежный* *розово-голубой* 💅",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )
    try:
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=STICKERS["angel"])
    except: pass

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_histories.pop(update.effective_user.id, None)
    await update.message.reply_text("История очищена 🍵✨", reply_markup=get_main_keyboard())

async def sticker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = random.choice(list(STICKERS.keys()))
    await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=STICKERS[key])

async def model_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Модель: `{GEMINI_MODEL}`\nБот: @Airy_Aibot 💗", parse_mode="Markdown", reply_markup=get_main_keyboard())

async def remember_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ' '.join(context.args) if context.args else ""
    if not text:
        profile = user_profiles.get(update.effective_user.id, {})
        await update.message.reply_text(f"Память: `{profile}`\n`/remember люблю...`", parse_mode="Markdown")
        return
    user_profiles[update.effective_user.id] = {"memory": text, "name": update.effective_user.first_name}
    await update.message.reply_text(f"Запомнил 💗: `{text}`", parse_mode="Markdown")

async def welcome_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Когда бота добавили в группу
    new_members = update.message.new_chat_members
    if any(m.id == context.bot.id for m in new_members):
        chat_title = update.effective_chat.title or "группу"
        await update.message.reply_text(
            f"Привет, *{chat_title}* 💗✨\n\n"
            f"Я *Airy* 🩷 — розовые волосы, синие глаза, рубашка с галстуком + кофточка 🌸\n"
            f"Буду помогать тут 🫶\n"
            f"Тегните меня `@Airy_Aibot` или ответьте на мое сообщение — отвечу 💅\n"
            f"Команды не нужны!",
            parse_mode="Markdown"
        )

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    fid = sticker.file_id
    emoji = sticker.emoji or ""
    desc = STICKER_EMOJI_MAP.get(fid, emoji)
    prompt = f"Пользователь отправил стикер {desc} {emoji}. Ответь мило, по теме стикера, 1-2 строки, эстетичными эмодзи 💗🩷✨. Можешь тоже кинуть стикер тегом [STICKER:xxx]"
    update.message.text = prompt
    await handle_message(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if text == "💗 О Airy":
        await about_cmd(update, context); return
    if text == "🌺 Помощь":
        await help_cmd(update, context); return
    if text == "🫐 Очистить":
        await clear(update, context); return
    if text == "✨ Модель":
        await model_info(update, context); return
    if update.effective_chat.type in ["group", "supergroup"]:
        bot_username = context.bot.username
        is_mention = f"@{bot_username}" in text
        is_reply_to_bot = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        if not (is_mention or is_reply_to_bot):
            return
        text = text.replace(f"@{bot_username}", "").strip()
        if not text:
            text = "привет"
    user_id = update.effective_user.id
    # Антиспам: не чаще 1 запроса в 2 сек
    import time
    now = time.time()
    if user_id in last_request_time and now - last_request_time[user_id] < 2:
        await update.message.reply_text("Подожди 2 сек 🍵✨", reply_markup=get_main_keyboard())
        return
    last_request_time[user_id] = now
    if user_id not in user_profiles:
        user_profiles[user_id] = {"name": update.effective_user.first_name, "username": update.effective_user.username}
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        if user_id not in chat_histories:
            chat_histories[user_id] = []
        history = chat_histories[user_id]
        profile = user_profiles.get(user_id, {})
        memory_str = f"Память: {profile}" if profile.get("memory") else f"Имя: {profile.get('name','друг')}"
        contents=[]
        if not history:
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=f"{SYSTEM_PROMPT}\n\n{memory_str}\n\nПользователь: {text}")]))
        else:
            for msg in history:
                contents.append(types.Content(role=msg["role"], parts=[types.Part.from_text(text=msg["text"])]))
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        def call_gemini():
            models_to_try=[GEMINI_MODEL,"gemini-3.6-flash","gemini-flash-latest","gemini-2.5-flash","gemini-2.0-flash"]
            safety = [
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            ]
            cfg = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, safety_settings=safety, temperature=0.9)
            last=None
            # пробуем все ключи при 429
            for ki in range(len(GEMINI_KEYS)):
                for m in dict.fromkeys(models_to_try):
                    try:
                        # используем текущий client (ротируется)
                        return client.models.generate_content(model=m, contents=contents, config=cfg)
                    except Exception as e:
                        es=str(e)
                        if "404" in es and "not found" in es.lower():
                            last=e; continue
                        if "429" in es or "quota" in es.lower() or "RESOURCE_EXHAUSTED" in es:
                            last=e
                            # пробуем следующий ключ
                            if ki < len(GEMINI_KEYS)-1:
                                rotate_key()
                                break # break моделей, пойдем на следующий ключ
                            else:
                                raise
                        raise
            raise last
        import asyncio
        # Ретрай при 429 с ожиданием
        for attempt in range(2):
            try:
                response=await asyncio.to_thread(call_gemini)
                break
            except Exception as e:
                if "429" in str(e) and attempt==0:
                    logger.warning("429 retry in 8s")
                    await asyncio.sleep(8)
                    continue
                raise
        answer=response.text
        history.append({"role":"user","text":text})
        history.append({"role":"model","text":answer})
        if len(history)>30:
            history[:]=history[-30:]
        clean=answer
        clean = re.sub(r"\[?\s*(?:sticker|stiker)\s*:\s*\w+\s*\]?", "", clean, flags=re.IGNORECASE).strip()
        clean = clean.replace("😂", "").replace("🤣", "")
        # === Конверт Markdown -> HTML для Telegram (чтобы не было ** звездочек) ===
        def md_to_html(text):
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            def repl_pre(m):
                return f"<pre>{m.group(1)}</pre>"
            text = re.sub(r"```(?:\w+)?\n?(.*?)\n?```", repl_pre, text, flags=re.DOTALL)
            text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
            text = re.sub(r"\*([^*]+?)\*", r"<b>\1</b>", text)
            text = re.sub(r"__(.+?)__", r"<i>\1</i>", text)
            return text
        html = md_to_html(clean)
        async def send_formatted(t):
            if len(t)>4096:
                for i in range(0,len(t),4096):
                    chunk=t[i:i+4096]
                    try:
                        await update.message.reply_text(chunk, parse_mode="HTML", reply_markup=get_main_keyboard())
                    except Exception as e:
                        logger.warning(f"html fail chunk {e}")
                        # fallback plain
                        txt = re.sub(r"<[^>]+>", "", chunk)
                        await update.message.reply_text(txt, reply_markup=get_main_keyboard())
            else:
                try:
                    await update.message.reply_text(t, parse_mode="HTML", reply_markup=get_main_keyboard())
                except Exception as e:
                    logger.warning(f"html fail {e} text={t[:200]}")
                    txt = re.sub(r"<[^>]+>", "", t)
                    await update.message.reply_text(txt, reply_markup=get_main_keyboard())
        await send_formatted(html)
        await send_sticker_if_needed(update.effective_chat.id, answer, context.bot)
    except Exception as e:
        err=str(e)
        logger.error(err)
        if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
            await update.message.reply_text("Лимит Gemini 🫐 Подожди 30 сек и попробуй снова 🍵\nЕсли часто — лимит 15 запросов/мин на бесплатном. Проверь https://aistudio.google.com", reply_markup=get_main_keyboard())
        elif "not supported" in err or "FAILED_PRECONDITION" in err:
            await update.message.reply_text("⚠️ Регион, на Render заработает 🌍", reply_markup=get_main_keyboard())
        elif "404" in err and "not found" in err.lower():
            await update.message.reply_text(f"⚠️ Модель {GEMINI_MODEL} не найдена", reply_markup=get_main_keyboard())
        else:
            await update.message.reply_text(f"Ошибка: {err[:800]}", reply_markup=get_main_keyboard())

def main():
    start_health_server()
    import time
    while True:
        try:
            app=Application.builder().token(BOT_TOKEN).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("help", help_cmd))
            app.add_handler(CommandHandler("about", about_cmd))
            app.add_handler(CommandHandler("clear", clear))
            app.add_handler(CommandHandler("remember", remember_cmd))
            app.add_handler(CommandHandler("sticker", sticker_cmd))
            app.add_handler(CommandHandler("model", model_info))
            app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_group))
            app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            print(f"Airy запущена на {GEMINI_MODEL}...")
            app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        except Exception as e:
            logger.error(f"Bot crashed: {e}, restart in 5s...")
            time.sleep(5)
if __name__=="__main__":
    main()
