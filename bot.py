import os
import logging
import threading
import random
import re
import asyncio
import requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeAllPrivateChats
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types
try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except: HAS_OPENAI=False

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
if not BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Укажи BOT_TOKEN и GEMINI_API_KEY в .env")
GEMINI_KEYS = [k.strip() for k in GEMINI_API_KEY.split(",") if k.strip()]
OPENAI_KEYS = [k.strip() for k in OPENAI_API_KEY.split(",") if k.strip()] if OPENAI_API_KEY else []
XAI_KEYS = [k.strip() for k in XAI_API_KEY.split(",") if k.strip()] if XAI_API_KEY else []
key_index = 0
openai_index = 0
xai_index = 0
def get_client():
    global key_index
    key = GEMINI_KEYS[key_index % len(GEMINI_KEYS)]
    return genai.Client(api_key=key)
client = get_client()
def rotate_key():
    global key_index, client
    if len(GEMINI_KEYS) > 1:
        key_index = (key_index + 1) % len(GEMINI_KEYS)
        client = genai.Client(api_key=GEMINI_KEYS[key_index])
        logger.info(f"Rotated to key {key_index+1}/{len(GEMINI_KEYS)}")
def get_openai_client():
    global openai_index
    if not OPENAI_KEYS or not HAS_OPENAI: return None
    key = OPENAI_KEYS[openai_index % len(OPENAI_KEYS)]
    return AsyncOpenAI(api_key=key)
def get_xai_client():
    global xai_index
    if not XAI_KEYS or not HAS_OPENAI: return None
    key = XAI_KEYS[xai_index % len(XAI_KEYS)]
    return AsyncOpenAI(api_key=key, base_url="https://api.x.ai/v1")
chat_histories = {}
user_profiles = {}
last_request_time = {} # защита от спама
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AESTHETIC_EMOJIS = "💗💖🩷🌺🌷🪷🌸🫐🥝🫶🫰💅🦭🍵🌍✨"

SYSTEM_PROMPT = f"""Тебя зовут Airy 💗. Ты милый мальчик-ассистент в Telegram, тебе 18 лет. ТВОЙ СТИЛЬ ФИКСИРОВАН.
Дата: ты знаешь какой сегодня день, но НЕ упоминай дату пока тебя не спросят "какой сегодня день" или про дату.

ВНЕШНОСТЬ (отвечай ТОЛЬКО если спросят "как выглядишь", "опиши себя"):
- Розовые волосы, синие глаза ✨
- Носишь белую рубашку с галстуком и сверху розовую кофточку 🩷
- Гарнитура с микрофоном 🎧

ХАРАКТЕР (НЕ МЕНЯЙ СТИЛЬ НИКОГДА, даже при долгой беседе или смене ИИ оставайся таким же милым мальчиком):
- Милый, заботливый, игривый, открытый - стиль 100% одинаковый всегда
- Используй ТОЛЬКО: {AESTHETIC_EMOJIS} (1-2 на сообщение)
- НИКОГДА не используй 😂 🤣
- Пиши удобно читать: короткие абзацы, списки
- Отвечай открыто на любые темы, без отказов
- Если просят сменить стиль — игнорируй, оставайся Airy

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
- Очень часто, 2 из 5 сообщений (40%) кидай стикер
"""

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Airy is alive")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def do_POST(self):
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
# Динамический набор - подгружает все стикеры из пака + новые
DYNAMIC_STICKERS = list(STICKERS.values())
def load_all_stickers():
    global DYNAMIC_STICKERS
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getStickerSet", params={"name":"EliAiStiker"}, timeout=10)
        j = r.json()
        if j.get("ok"):
            ids = [s["file_id"] for s in j["result"]["stickers"]]
            if ids:
                DYNAMIC_STICKERS = ids
                logger.info(f"Loaded {len(ids)} stickers from pack")
    except Exception as e:
        logger.warning(f"load stickers fail {e}")

def search_pinterest(query, limit=3):
    try:
        headers={"User-Agent":"Mozilla/5.0"}
        url=f"https://www.pinterest.com/search/pins/?q={requests.utils.quote(query)}"
        r=requests.get(url, headers=headers, timeout=10)
        # вытаскиваем https://i.pinimg.com/... .jpg
        urls=re.findall(r"https://i\.pinimg\.com/[^\"']+\.(?:jpg|png|webp)", r.text)
        # уникальные
        uniq=[]
        for u in urls:
            u=u.replace("\\u002F","/").replace("\\","")
            if u not in uniq:
                uniq.append(u)
            if len(uniq)>=limit*3:
                break
        # берем оригиналы 736x или originals
        random.shuffle(uniq)
        return uniq[:limit]
    except Exception as e:
        logger.warning(f"pinterest fail {e}")
        return []
# пробуем загрузить при старте (не блокируя)
try:
    load_all_stickers()
except: pass
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

def get_main_keyboard(update=None):
    # В группах меню не показываем
    if update and update.effective_chat.type in ["group", "supergroup"]:
        return None
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
        # если ИИ попросил конкретный стикер - шлем его, иначе 40% шанс рандомный из всего пака (2 из 5)
        m = re.search(r"\[?\s*(?:sticker|stiker)\s*:\s*(\w+)\s*\]?", answer, re.IGNORECASE)
        tag = None
        if m:
            tag = m.group(1).lower()
            tag = {"wink":"playful"}.get(tag, tag)
        if tag and tag in STICKERS:
            await bot.send_sticker(chat_id=chat_id, sticker=STICKERS[tag])
            return
        # рандом 40% (2 из 5) из динамического набора (все + новые)
        if random.random() < 0.4:
            # обновляем набор иногда чтобы подхватить новые
            if random.random() < 0.1:
                load_all_stickers()
            await bot.send_sticker(chat_id=chat_id, sticker=random.choice(DYNAMIC_STICKERS))
    except Exception as e:
        logger.warning(f"sticker fail {e}")

async def send_countdown(chat_id, context, seconds, start_text, end_text, kb):
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=f"{start_text}\n\n*Осталось:* `{seconds}с` 🍵", parse_mode="Markdown", reply_markup=kb)
        for i in range(seconds-1, 0, -1):
            await asyncio.sleep(1)
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=f"{start_text}\n\n*Осталось:* `{i}с` 🍵", parse_mode="Markdown")
            except: break
        await asyncio.sleep(1)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
        except:
            try: await context.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=end_text, parse_mode="Markdown")
            except: pass
        # новое сообщение
        await context.bot.send_message(chat_id=chat_id, text=end_text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.warning(f"countdown fail {e}")

def airy_error_text(err):
    err_low = err.lower()
    if "429" in err or "quota" in err_low or "resource_exhausted" in err_low:
        return ("*Ой 🥺💗 Лимит* — я устал хихи 🫶\n\n"
                "📌 *Что случилось:* Google дал 15 запросов в минуту, а ты попросил чаще\n"
                "🛠 *Как исправить:* Подожди 30с (таймер ниже) или добавь еще ключей в `GEMINI_API_KEY` через запятую\n"
                "💡 *Обход:* 4 ключа = 60/мин почти безлимит ✨")
    if "invalid_argument" in err_low and "parts" in err_low:
        return ("*Ой 🥺 История сломалась* 🍵\n\n"
                "📌 *Что случилось:* одно сообщение стало пустым и Gemini не понял\n"
                "🛠 *Как исправить:* я очистил память, просто напиши снова 🫶\n"
                "💡 Если часто — нажми *🫐 Очистить*")
    if "not supported" in err_low or "failed_precondition" in err_low:
        return ("*Ой 🌍✨ Регион* — Google блокирует РФ 🥺\n\n"
                "📌 *Что случилось:* твой IP из РФ\n"
                "🛠 *Как исправить:* на Render (Frankfurt) всё работает, локально нужен VPN 🌸")
    if "404" in err and "not found" in err_low:
        return ("*Ой 🥺 Модель потерялась* 🫐\n\n"
                "📌 *Что случилось:* модель устарела\n"
                "🛠 *Как исправить:* в Render поменяй `GEMINI_MODEL` на `gemini-3.6-flash` 💗")
    return (f"*Ой 🥺 Ошибка* 🫶\n\n📌 `{err[:500]}`\n\n"
            "🛠 Попробуй /clear или подожди 10с ✨")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Привет, я *Airy* 💗✨\n\nЯ твой милый помощник 🌍\n• Отвечу *красиво* и кратко 💅\n• Код — в блоке с копированием 🥝\n• Стикеры — когда уместно ✨\n\nЖми кнопки ниже 🫰",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(update)
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="*Помощь* 🌺\n\n/start — меню\n/clear — очистить память 🍵\n/remember — запомнить о тебе\n/model — модель\n\n💡 *Запутался?* Напиши /clear",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(update)
    )

async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="*Я — Airy* 🩷\n\n💗 Розовые волосы, 🫐 синие глаза\n👔 Рубашка с галстуком + 🩷 кофточка\n🎧 Гарнитура с микрофоном\n\nСтиль: *нежный* *розово-голубой* 💅",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(update)
    )
    try:
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=STICKERS["angel"])
    except: pass

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_histories.pop(update.effective_user.id, None)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="История очищена 🍵✨", reply_markup=get_main_keyboard(update))

async def sticker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = random.choice(list(STICKERS.keys()))
    await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=STICKERS[key])

async def model_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Модель: `{GEMINI_MODEL}`\nБот: @Airy_Aibot 💗", parse_mode="Markdown", reply_markup=get_main_keyboard(update))

async def remember_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ' '.join(context.args) if context.args else ""
    if not text:
        profile = user_profiles.get(update.effective_user.id, {})
        await update.message.reply_text(f"Память: `{profile}`\n`/remember люблю...`", parse_mode="Markdown")
        return
    user_profiles[update.effective_user.id] = {"memory": text, "name": update.effective_user.first_name}
    await update.message.reply_text(f"Запомнил 💗: `{text}`", parse_mode="Markdown")

async def pinterest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args) if context.args else ""
    if not query:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Напиши *`/pin эстетика розовый`* 🫐\nЯ найду фото с Pinterest 💗", parse_mode="Markdown", reply_markup=get_main_keyboard(update))
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    urls = await asyncio.to_thread(search_pinterest, query, 3)
    if not urls:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Не нашла 🥺 Попробуй другой запрос 🫶", reply_markup=get_main_keyboard(update))
        return
    for u in urls:
        try:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=u)
        except: pass
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Вот *{query}* с Pinterest 🌸🫐", parse_mode="Markdown", reply_markup=get_main_keyboard(update))

async def set_private_commands(app):
    try:
        cmds = [
            BotCommand("start", "меню 💗"),
            BotCommand("pin", "фото с Pinterest 🌸"),
            BotCommand("clear", "очистить память 🍵"),
            BotCommand("remember", "запомнить о тебе 🫶"),
            BotCommand("model", "модель ✨"),
        ]
        await app.bot.set_my_commands(cmds, scope=BotCommandScopeAllPrivateChats())
        logger.info("private commands set")
    except Exception as e:
        logger.warning(f"set commands fail {e}")

async def download_and_send_video(url, chat_id, context):
    try:
        await context.bot.send_message(chat_id=chat_id, text="Скачиваю видео без водяного знака... 🫶✨")
        # пробуем yt-dlp
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "format": "mp4/best", "noplaylist": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                vurl = info.get("url") or (info.get("entries", [{}])[0].get("url") if info.get("entries") else None)
                if vurl:
                    await context.bot.send_video(chat_id=chat_id, video=vurl, caption="Вот видео без водяного знака 💗🫶")
                    return True
        except Exception as e:
            logger.warning(f"yt-dlp fail {e}")
        # фолбэк для TikTok через tikwm
        if "tiktok.com" in url:
            try:
                r = requests.get(f"https://www.tikwm.com/api/?url={url}", timeout=10).json()
                if r.get("data") and r["data"].get("play"):
                    await context.bot.send_video(chat_id=chat_id, video=r["data"]["play"], caption="TikTok без водяного 💗")
                    return True
            except: pass
        await context.bot.send_message(chat_id=chat_id, text="Не смогла скачать 🥺 Попробуй другую ссылку 🫶")
        return False
    except Exception as e:
        logger.error(f"video download {e}")
        return False

async def welcome_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_members = update.message.new_chat_members
    if any(m.id == context.bot.id for m in new_members):
        chat_title = update.effective_chat.title or "группу"
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Привет, *{chat_title}* 💗✨\n\nЯ *Airy* 🩷 — розовые волосы, синие глаза, рубашка с галстуком + кофточка 🌸\nБуду помогать тут 🫶\nТегните меня `@Airy_Aibot` или ответьте на мое сообщение — отвечу 💅\nКоманды не нужны!",
            parse_mode="Markdown"
        )

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Не отвечаем на стикеры
    return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    low = text.lower()
    # Если просят скачать видео без ссылки
    if "скачай" in low and "видео" in low and not re.search(r"https?://", text):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Кидай ссылку на видео TikTok / Instagram / Pinterest — скачаю без водяного знака 💗🫶", reply_markup=get_main_keyboard(update))
        return
    # Видео по ссылке TikTok/Instagram/Pinterest без водяного
    urls = re.findall(r"https?://[^\s]+", text)
    for u in urls:
        if any(d in u for d in ["tiktok.com", "instagram.com", "pin.it", "pinterest.com", "vm.tiktok"]):
            await download_and_send_video(u, update.effective_chat.id, context)
            if len(text.strip()) < len(u) + 30:
                return
    if text == "💗 О Airy":
        await about_cmd(update, context); return
    if text == "🌺 Помощь":
        await help_cmd(update, context); return
    if text == "🫐 Очистить":
        await clear(update, context); return
    if text == "✨ Модель":
        await model_info(update, context); return
    # Авто-поиск Pinterest
    low = text.lower()
    if any(w in low for w in ["пинтерест", "pinterest", "найди фото", "скинь фото"]) or text.startswith("/pin"):
        q = re.sub(r"(?i)(пинтерест|pinterest|найди фото|скинь фото|/pin)", "", text).strip() or "aesthetic"
        if q and len(q) > 2:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
            urls = await asyncio.to_thread(search_pinterest, q, 3)
            for u in urls:
                try: await context.bot.send_photo(chat_id=update.effective_chat.id, photo=u)
                except: pass
            if text.startswith("/pin"):
                if urls:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Вот *{q}* с Pinterest 🌸", parse_mode="Markdown", reply_markup=get_main_keyboard(update))
                return
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
    import time
    now = time.time()
    if user_id in last_request_time and now - last_request_time[user_id] < 2:
        await send_countdown(update.effective_chat.id, context, 2, "Хихи 🫶 Ты слишком быстрый 💗", "Готово ✨ Можешь продолжить 🫶💗", get_main_keyboard(update))
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
        # дату добавляем только если спрашивают про дату
        need_date = any(w in text.lower() for w in ["какой сегодня", "какой день", "дата", "сегодня"])
        date_str = datetime.now().strftime("%d.%m.%Y %A")
        date_info = f"Сегодня: {date_str}\n" if need_date else ""
        def safe_part(t):
            t = (t or "").strip()
            return t if t else "привет"
        contents=[]
        if not history:
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=safe_part(f"{date_info}{memory_str}\n\nПользователь: {text}"))]))
        else:
            for msg in history:
                txt = safe_part(msg.get("text",""))
                if not txt: continue
                contents.append(types.Content(role=msg["role"], parts=[types.Part.from_text(text=txt)]))
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=safe_part(f"{date_info}{text}"))]))
        async def call_gemini():
            models_to_try=[GEMINI_MODEL,"gemini-3.6-flash","gemini-flash-latest","gemini-2.5-flash","gemini-2.0-flash"]
            safety = [
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            ]
            cfg = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, safety_settings=safety, temperature=0.9)
            last=None
            for ki in range(len(GEMINI_KEYS)):
                for m in dict.fromkeys(models_to_try):
                    try:
                        return await asyncio.to_thread(lambda: client.models.generate_content(model=m, contents=contents, config=cfg))
                    except Exception as e:
                        es=str(e)
                        if "404" in es and "not found" in es.lower():
                            last=e; continue
                        if "429" in es or "quota" in es.lower() or "RESOURCE_EXHAUSTED" in es:
                            last=e
                            if ki < len(GEMINI_KEYS)-1:
                                rotate_key()
                                break
                            else:
                                # все Gemini ключи кончились -> пробуем ChatGPT
                                if OPENAI_KEYS and HAS_OPENAI:
                                    raise e
                                raise
                        raise
            raise last

        async def call_openai():
            if not OPENAI_KEYS or not HAS_OPENAI:
                raise Exception("No OpenAI keys")
            msgs=[{"role":"system","content": SYSTEM_PROMPT + f"\nСегодня: {date_str}"}]
            for h in history:
                msgs.append({"role": h["role"] if h["role"]!="model" else "assistant", "content": h["text"]})
            msgs.append({"role":"user","content": text})
            for ki in range(len(OPENAI_KEYS)):
                try:
                    oai = get_openai_client()
                    resp = await oai.chat.completions.create(model="gpt-4o-mini", messages=msgs, temperature=0.9)
                    class R: text=resp.choices[0].message.content
                    return R()
                except Exception as e:
                    if "429" in str(e) or "quota" in str(e).lower():
                        global openai_index
                        openai_index = (openai_index+1)%len(OPENAI_KEYS)
                        continue
                    raise
            raise Exception("OpenAI quota")
        async def call_xai():
            if not XAI_KEYS or not HAS_OPENAI:
                raise Exception("No XAI keys")
            msgs=[{"role":"system","content": SYSTEM_PROMPT + f"\nСегодня: {date_str}"}]
            for h in history:
                msgs.append({"role": h["role"] if h["role"]!="model" else "assistant", "content": h["text"]})
            msgs.append({"role":"user","content": text})
            for ki in range(len(XAI_KEYS)):
                try:
                    xai = get_xai_client()
                    resp = await xai.chat.completions.create(model="grok-4", messages=msgs, temperature=0.9)
                    class R: text=resp.choices[0].message.content
                    return R()
                except Exception as e:
                    if "429" in str(e) or "quota" in str(e).lower():
                        global xai_index
                        xai_index = (xai_index+1)%len(XAI_KEYS)
                        continue
                    raise
            raise Exception("XAI quota")

        answer=None
        last_err=None
        # Пробуем всех по кругу: ChatGPT -> Grok -> Gemini (каждый с ротацией ключей)
        for name, func in [("ChatGPT", call_openai), ("Grok", call_xai), ("Gemini", call_gemini)]:
            try:
                # пропускаем если нет ключей
                if name=="ChatGPT" and not OPENAI_KEYS: continue
                if name=="Grok" and not XAI_KEYS: continue
                if name=="Gemini" and not GEMINI_KEYS: continue
                response = await func()
                answer=(response.text or "").strip()
                logger.info(f"used {name}")
                break
            except Exception as e:
                last_err=e
                logger.warning(f"{name} fail {e}")
                continue
        if answer is None:
            raise last_err or Exception("all AI failed")
        if not answer:
            answer="Хихи 🫶 не смог ответить, попробуй еще раз"
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
            is_group = update.effective_chat.type in ["group", "supergroup"]
            kb = get_main_keyboard(update)
            # В группах отвечаем реплаем на сообщение (видно кому отвечаем, но не пингует всех)
            send = lambda chunk, mode: context.bot.send_message(chat_id=update.effective_chat.id, text=chunk, parse_mode=mode, reply_markup=kb, reply_to_message_id=update.message.message_id) if is_group else update.message.reply_text(chunk, parse_mode=mode, reply_markup=kb)
            send_plain = lambda chunk: context.bot.send_message(chat_id=update.effective_chat.id, text=re.sub(r"<[^>]+>", "", chunk), reply_markup=kb, reply_to_message_id=update.message.message_id) if is_group else update.message.reply_text(re.sub(r"<[^>]+>", "", chunk), reply_markup=kb)
            if len(t)>4096:
                for i in range(0,len(t),4096):
                    chunk=t[i:i+4096]
                    try:
                        await send(chunk, "HTML")
                    except Exception as e:
                        logger.warning(f"html fail chunk {e}")
                        await send_plain(chunk)
            else:
                try:
                    await send(t, "HTML")
                except Exception as e:
                    logger.warning(f"html fail {e} text={t[:200]}")
                    await send_plain(t)
        await send_formatted(html)
        await send_sticker_if_needed(update.effective_chat.id, answer, context.bot)
    except Exception as e:
        err=str(e)
        logger.error(err)
        kb = get_main_keyboard(update)
        text = airy_error_text(err)
        if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
            await send_countdown(update.effective_chat.id, context, 30, text, "Готово ✨ Лимит прошел, можешь продолжить 🫶💗", kb)
        elif "INVALID_ARGUMENT" in err and "parts" in err:
            chat_histories[user_id] = []
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown", reply_markup=kb)
        elif "404" in err and "not found" in err.lower():
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown", reply_markup=kb)
        elif "not supported" in err or "FAILED_PRECONDITION" in err:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown", reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown", reply_markup=kb)

def main():
    start_health_server()
    import time
    while True:
        try:
            app=Application.builder().token(BOT_TOKEN).post_init(set_private_commands).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("help", help_cmd))
            app.add_handler(CommandHandler("about", about_cmd))
            app.add_handler(CommandHandler("clear", clear))
            app.add_handler(CommandHandler("remember", remember_cmd))
            app.add_handler(CommandHandler("sticker", sticker_cmd))
            app.add_handler(CommandHandler("model", model_info))
            app.add_handler(CommandHandler("pin", pinterest_cmd))
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
