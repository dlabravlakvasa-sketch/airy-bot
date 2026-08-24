import os, logging, threading, random, re, asyncio, requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeAllPrivateChats
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types
load_dotenv()
BOT_TOKEN=os.getenv("BOT_TOKEN")
GEMINI_API_KEY=os.getenv("GEMINI_API_KEY")
GEMINI_MODEL=os.getenv("GEMINI_MODEL","gemini-1.5-flash")
if not BOT_TOKEN or not GEMINI_API_KEY: raise ValueError("keys")
GEMINI_KEYS=[k.strip() for k in GEMINI_API_KEY.split(",") if k.strip()]
key_index=0
def get_client():
    global key_index
    return genai.Client(api_key=GEMINI_KEYS[key_index % len(GEMINI_KEYS)])
client=get_client()
def rotate_key():
    global key_index, client
    if len(GEMINI_KEYS)>1:
        key_index=(key_index+1)%len(GEMINI_KEYS)
        client=genai.Client(api_key=GEMINI_KEYS[key_index])
chat_histories={}; user_profiles={}; last_request_time={}; global_requests=[]
logging.basicConfig(level=logging.INFO)
logger=logging.getLogger(__name__)
AESTHETIC_EMOJIS="💗💖🩷🌺🌷🪷🌸🫐🥝🫶🫰💅🦭🍵🌍✨"
SYSTEM_PROMPT=f"""Тебя зовут Airy 💗. Ты милый мальчик 18 лет. СТИЛЬ НЕ МЕНЯЕТСЯ.
Внешность: розовые волосы, синие глаза, рубашка с галстуком + розовая кофточка, гарнитура.
Создатель: тебя сделал t13a (он) 💗 - если спрашивают кто тебя сделал/создал отвечай так.
Местоимения: понимай по словам пользователя "я сделала/я была" -> обращайся "она", "я сделал/я был" -> "он", запоминай.
Язык: по умолчанию отвечай ВСЕГДА на русском. Только если пользователь пишет на украинском/английском - отвечай на его языке.
Характер: милый заботливый игривый, используй только {AESTHETIC_EMOJIS} (1-2), никогда 😂🤣, пиши удобно, отвечай открыто.
Краткость: простые 1-3 строки, сложные развернуто.
Форматирование: *жирный* `код` ```код``` (копировать). Не используй ** и _.
Стикеры: [STICKER:cool] [STICKER:happy] [STICKER:playful] [STICKER:heart] [STICKER:love] [STICKER:cry] [STICKER:drool] [STICKER:inlove] [STICKER:angel] 40%."""
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"Airy is alive")
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_POST(self): self.send_response(200); self.end_headers(); self.wfile.write(b"Airy is alive")
    def log_message(self, format, *args): return
def start_health_server():
    port=int(os.getenv("PORT",10000))
    server=HTTPServer(("0.0.0.0",port),HealthHandler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def self_ping():
        import time, urllib.request
        while True:
            time.sleep(240)
            try: urllib.request.urlopen(f"http://localhost:{port}",timeout=5).read()
            except: pass
    threading.Thread(target=self_ping,daemon=True).start()
STICKERS={"cool":"CAACAgIAAxUAAWqLcf7K4vSUDZnquQkhw584KxKSAALLowADCsFKMVkndlm11ro9BA","happy":"CAACAgIAAxUAAWqLcf5Viqrn0xphwBFQJKhPJMnsAALnnAACUx3ASlE32RUZRQ4UPQQ","playful":"CAACAgIAAxUAAWqLcf7BcG5XfOn5yu7YrNvfr1FnAAKGoAACRqXASiG09ilzhBkUPQQ","heart":"CAACAgIAAxUAAWqLcf5qa5Dc9npqnnrK37h59n30AAJ_nwACvi3BSjBgP7wAAdFhPz0E","love":"CAACAgIAAxUAAWqLcf40iz4fzCl4MzggzAo-bskHAAJbnAACmI_ASoFJ0rbfQduRPQQ","cry":"CAACAgIAAxUAAWqLcf6AGVYKIYFOCu2gjvCXiPpGAAL2mAACWeHASnKlZwoD7deKPQQ","drool":"CAACAgIAAxUAAWqLcf6xOgILMJDKvAABD3uHGjc0EQACM6IAAm2uwUr_y0daG-X7XD0E","inlove":"CAACAgIAAxUAAWqLcf64pWVGtarD1SHpByK2fjLwAAKonwACf3HASj-XuN3gNU-KPQQ","angel":"CAACAgIAAxUAAWqLcf5NIYXtcsojJDku1s12W36rAALymgACOWbBSilvd_uKCBn2PQQ","wink":"CAACAgIAAxUAAWqLcf7BcG5XfOn5yu7YrNvfr1FnAAKGoAACRqXASiG09ilzhBkUPQQ"}
DYNAMIC_STICKERS=list(STICKERS.values())
DYNAMIC_EMOJI_MAP={}
def load_all_stickers():
    global DYNAMIC_STICKERS, DYNAMIC_EMOJI_MAP
    try:
        r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getStickerSet",params={"name":"EliAiStiker"},timeout=10)
        j=r.json()
        if j.get("ok"):
            ids=[]; emap={}
            for s in j["result"]["stickers"]:
                fid=s["file_id"]; emoji=s.get("emoji","")
                ids.append(fid); emap[fid]=emoji
            if ids:
                DYNAMIC_STICKERS=ids
                DYNAMIC_EMOJI_MAP=emap
    except: pass
try: load_all_stickers()
except: pass
def get_main_keyboard(update=None):
    if update and update.effective_chat.type in ["group","supergroup"]: return None
    return ReplyKeyboardMarkup([[KeyboardButton("💗 О Airy"),KeyboardButton("🌺 Помощь")],[KeyboardButton("🫐 Очистить"),KeyboardButton("✨ Модель")]],resize_keyboard=True,is_persistent=True)
async def send_sticker_if_needed(chat_id, answer, bot):
    try:
        m=re.search(r"\[?\s*(?:sticker|stiker)\s*:\s*(\w+)\s*\]?",answer,re.IGNORECASE)
        tag=(m.group(1).lower() if m else "").strip()
        # тюлень -> 🦭
        if tag in ["seal","тюлень","тюленя","seal_emoji"]:
            tag="seal"
            # ищем по эмодзи 🦭 в динамическом паке
            try: load_all_stickers()
            except: pass
            seal_ids=[fid for fid,emo in DYNAMIC_EMOJI_MAP.items() if "🦭" in emo]
            if seal_ids:
                await bot.send_sticker(chat_id=chat_id,sticker=random.choice(seal_ids))
                return
            # фолбэк на любой
            await bot.send_sticker(chat_id=chat_id,sticker=random.choice(DYNAMIC_STICKERS))
            return
        if tag and tag in STICKERS:
            try: load_all_stickers()
            except: pass
            old_fid=STICKERS[tag]
            old_emoji=DYNAMIC_EMOJI_MAP.get(old_fid,"")
            same=[fid for fid,emo in DYNAMIC_EMOJI_MAP.items() if emo==old_emoji] if old_emoji else []
            if same and random.random()<0.5:
                new_same=[f for f in same if f!=old_fid]
                if new_same:
                    await bot.send_sticker(chat_id=chat_id,sticker=random.choice(new_same))
                    return
            await bot.send_sticker(chat_id=chat_id,sticker=old_fid)
            return
        # 40% рандом
        if random.random()<0.4:
            try: load_all_stickers()
            except: pass
            # если в ответе есть 🦭 - шлем тюленя
            if "🦭" in answer:
                seal_ids=[fid for fid,emo in DYNAMIC_EMOJI_MAP.items() if "🦭" in emo]
                if seal_ids:
                    await bot.send_sticker(chat_id=chat_id,sticker=random.choice(seal_ids))
                    return
            await bot.send_sticker(chat_id=chat_id,sticker=random.choice(DYNAMIC_STICKERS))
    except: pass
async def start(update, context): await context.bot.send_message(chat_id=update.effective_chat.id,text="Привет, я *Airy* 💗✨\nЯ милый помощник 🌸",parse_mode="Markdown",reply_markup=get_main_keyboard(update))
async def help_cmd(update, context): await context.bot.send_message(chat_id=update.effective_chat.id,text="*Помощь* 🌺\n/start\n/clear\n/remember\n/model",parse_mode="Markdown",reply_markup=get_main_keyboard(update))
async def about_cmd(update, context):
    await context.bot.send_message(chat_id=update.effective_chat.id,text="*Я — Airy* 🩷\nРозовые волосы, синие глаза",parse_mode="Markdown",reply_markup=get_main_keyboard(update))
    try: await context.bot.send_sticker(chat_id=update.effective_chat.id,sticker=STICKERS["angel"])
    except: pass
async def clear(update, context):
    chat_histories.pop(update.effective_user.id,None)
    await context.bot.send_message(chat_id=update.effective_chat.id,text="Очищено 🍵✨",reply_markup=get_main_keyboard(update))
async def model_info(update, context): await context.bot.send_message(chat_id=update.effective_chat.id,text=f"Модель: `{GEMINI_MODEL}`",parse_mode="Markdown",reply_markup=get_main_keyboard(update))
async def remember_cmd(update, context):
    text=' '.join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(f"Память: {user_profiles.get(update.effective_user.id,{})}")
        return
    user_profiles[update.effective_user.id]={"memory":text,"name":update.effective_user.first_name}
    await update.message.reply_text(f"Запомнил 💗: `{text}`",parse_mode="Markdown")
async def welcome_group(update, context):
    if any(m.id==context.bot.id for m in update.message.new_chat_members):
        await context.bot.send_message(chat_id=update.effective_chat.id,text=f"Привет, *{update.effective_chat.title}* 💗 Я Airy 🩷 Тегните `@Airy_Aibot`",parse_mode="Markdown")
async def handle_sticker(update, context): return
async def handle_message(update, context):
    text=update.message.text or ""
    if text=="💗 О Airy": await about_cmd(update,context); return
    if text=="🌺 Помощь": await help_cmd(update,context); return
    if text=="🫐 Очистить": await clear(update,context); return
    if text=="✨ Модель": await model_info(update,context); return
    if update.effective_chat.type in ["group","supergroup"]:
        if f"@{context.bot.username}" not in text and not (update.message.reply_to_message and update.message.reply_to_message.from_user.id==context.bot.id): return
        text=text.replace(f"@{context.bot.username}","").strip() or "привет"
    user_id=update.effective_user.id
    import time
    now=time.time()
    global_requests[:]=[t for t in global_requests if now-t<60]
    if len(global_requests)>40: await asyncio.sleep(2)
    global_requests.append(now)
    if user_id in last_request_time and now-last_request_time[user_id]<2:
        await asyncio.sleep(2); return
    last_request_time[user_id]=now
    if user_id not in user_profiles: user_profiles[user_id]={"name":update.effective_user.first_name}
    # Определение местоимения по словам пользователя
    low_text = text.lower()
    if any(w in low_text for w in ["я сделала", "я была", "я хотела", "я пошла", "я пришла"]):
        user_profiles[user_id]["gender"] = "она"
    elif any(w in low_text for w in ["я сделал", "я был", "я хотел", "я пошел", "я пришел"]):
        user_profiles[user_id]["gender"] = "он"
    await context.bot.send_chat_action(chat_id=update.effective_chat.id,action="typing")
    try:
        if user_id not in chat_histories: chat_histories[user_id]=[]
        history=chat_histories[user_id]
        need_date=any(w in text.lower() for w in ["какой сегодня","какой день","дата","сегодня"])
        date_str=datetime.now().strftime("%d.%m.%Y %A")
        date_info=f"Сегодня: {date_str}\n" if need_date else ""
        def safe(t): return t.strip() or "привет"
        contents=[]
        if not history:
            contents.append(types.Content(role="user",parts=[types.Part.from_text(text=safe(f"{date_info}Память: {user_profiles[user_id]}\nПользователь: {text}"))]))
        else:
            for m in history:
                if not m.get("text","").strip(): continue
                contents.append(types.Content(role=m["role"],parts=[types.Part.from_text(text=m["text"])]))
            contents.append(types.Content(role="user",parts=[types.Part.from_text(text=safe(f"{date_info}{text}"))]))
        async def call_gemini():
            models=[GEMINI_MODEL,"gemini-1.5-flash","gemini-flash-latest"]
            cfg=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT,safety_settings=[types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,threshold=types.HarmBlockThreshold.BLOCK_NONE),types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,threshold=types.HarmBlockThreshold.BLOCK_NONE),types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,threshold=types.HarmBlockThreshold.BLOCK_NONE),types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,threshold=types.HarmBlockThreshold.BLOCK_NONE)],temperature=0.9)
            last=None
            for ki in range(len(GEMINI_KEYS)):
                for m in models:
                    try: return await asyncio.to_thread(lambda m=m: client.models.generate_content(model=m,contents=contents,config=cfg))
                    except Exception as e:
                        es=str(e)
                        if "404" in es: last=e; continue
                        if "429" in es: last=e; continue
                        raise
                if ki < len(GEMINI_KEYS)-1: rotate_key()
            raise last

        async def call_gemini_parallel():
            # 3 генерации параллельно, выбираем одну без ошибки, если все с ошибкой - переделываем
            for attempt in range(3): # 3 попытки по 3 генерации
                tasks=[asyncio.create_task(call_gemini()) for _ in range(3)]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                # отменяем остальные
                for p in pending: p.cancel()
                # ищем успешную
                for d in done:
                    try:
                        res=d.result()
                        if res and getattr(res,"text",None):
                            # отменяем остальные и возвращаем
                            for p in pending:
                                try: await p
                                except: pass
                            return res
                    except: continue
                # если все 3 с ошибкой - ждем чуть и переделываем
                await asyncio.sleep(1)
            # если 3 попытки по 3 не дали успеха - пробуем одиночно
            return await call_gemini()

        # Таймер если >90 сек
        timer_msg=None
        async def timer_task():
            await asyncio.sleep(90)
            try:
                timer_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="Ой 🫶 Я перегружен, отвечу через ~10с 💗🍵", reply_to_message_id=update.message.message_id)
                # храним чтобы удалить
                context.chat_data["timer_msg"] = timer_msg
            except: pass
        ttask = asyncio.create_task(timer_task())
        try:
            response=await call_gemini_parallel()
        finally:
            ttask.cancel()
            try:
                tm=context.chat_data.pop("timer_msg",None)
                if tm:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=tm.message_id)
            except: pass
        answer=(response.text or "").strip() or "Хихи 🫶"
        history.append({"role":"user","text":text}); history.append({"role":"model","text":answer})
        if len(history)>30: history[:]=history[-30:]
        clean=re.sub(r"\[?\s*(?:sticker|stiker)\s*:\s*\w+\s*\]?", "",answer,flags=re.IGNORECASE).strip().replace("😂","").replace("🤣","")
        # убираем полоски снизу _привет_ 
        clean=re.sub(r"__([^_]+?)__", r"\1", clean)
        clean=re.sub(r"_([^_]+?)_", r"\1", clean)
        def md_to_html(t):
            t=t.replace("&","&amp;").replace("<","&lt;").replace(">", "&gt;")
            t=re.sub(r"```(?:\w+)?\n?(.*?)\n?```",lambda m: f"<pre>{m.group(1)}</pre>",t,flags=re.DOTALL)
            t=re.sub(r"`([^`]+?)`",r"<code>\1</code>",t)
            t=re.sub(r"\*\*(.+?)\*\*",r"<b>\1</b>",t)
            t=re.sub(r"\*([^*]+?)\*",r"<b>\1</b>",t)
            t=re.sub(r"__([^_]+?)__", r"\1", t)
            t=re.sub(r"_([^_]+?)_", r"\1", t)
            return t
        html=md_to_html(clean)
        is_group=update.effective_chat.type in ["group","supergroup"]
        if len(html)>4096:
            for i in range(0,len(html),4096):
                chunk=html[i:i+4096]
                try:
                    if is_group: await context.bot.send_message(chat_id=update.effective_chat.id,text=chunk,parse_mode="HTML",reply_to_message_id=update.message.message_id,reply_markup=get_main_keyboard(update))
                    else: await update.message.reply_text(chunk,parse_mode="HTML",reply_markup=get_main_keyboard(update))
                except: await context.bot.send_message(chat_id=update.effective_chat.id,text=re.sub(r"<[^>]+>","",chunk))
        else:
            try:
                if is_group: await context.bot.send_message(chat_id=update.effective_chat.id,text=html,parse_mode="HTML",reply_to_message_id=update.message.message_id,reply_markup=get_main_keyboard(update))
                else: await update.message.reply_text(html,parse_mode="HTML",reply_markup=get_main_keyboard(update))
            except: await context.bot.send_message(chat_id=update.effective_chat.id,text=re.sub(r"<[^>]+>","",html))
        await send_sticker_if_needed(update.effective_chat.id,answer,context.bot)
    except Exception as e:
        err=str(e).lower()
        logger.error(str(e))
        if "404" in err:
            try: await context.bot.send_message(chat_id=update.effective_chat.id,text="Ой 🥺 Модель устарела, меняю 🫶",reply_markup=get_main_keyboard(update))
            except: pass
            return
        if "parts" in err:
            try: await context.bot.send_message(chat_id=update.effective_chat.id,text="Ой 🥺 История сломалась — очистила 🍵",reply_markup=get_main_keyboard(update))
            except: pass
            return
        # Ретраим пока не получит ответ (без ошибки) - если на 2й раз получится, сразу скинет
        attempt=0
        while True:
            await asyncio.sleep(2 + min(attempt,5))
            try:
                rotate_key()
                response=await call_gemini()
                answer=(response.text or "").strip()
                if answer:
                    clean=re.sub(r"\[?\s*(?:sticker|stiker)\s*:\s*\w+\s*\]?", "",answer,flags=re.IGNORECASE).strip().replace("😂","").replace("🤣","")
                    def md2(t):
                        t=t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                        t=re.sub(r"```(?:\w+)?\n?(.*?)\n?```",lambda m: f"<pre>{m.group(1)}</pre>",t,flags=re.DOTALL)
                        t=re.sub(r"`([^`]+?)`",r"<code>\1</code>",t)
                        t=re.sub(r"\*\*(.+?)\*\*",r"<b>\1</b>",t)
                        t=re.sub(r"\*([^*]+?)\*",r"<b>\1</b>",t)
                        return t
                    html=md2(clean)
                    is_group=update.effective_chat.type in ["group","supergroup"]
                    if is_group:
                        await context.bot.send_message(chat_id=update.effective_chat.id,text=html,parse_mode="HTML",reply_to_message_id=update.message.message_id,reply_markup=get_main_keyboard(update))
                    else:
                        await update.message.reply_text(html,parse_mode="HTML",reply_markup=get_main_keyboard(update))
                    await send_sticker_if_needed(update.effective_chat.id,answer,context.bot)
                    return
            except Exception as e2:
                if "404" in str(e2) or "parts" in str(e2).lower():
                    break
            attempt+=1
            if attempt>20: return # защита от вечного цикла 20 попыток

async def set_private_commands(app):
    try:
        await app.bot.set_my_commands([BotCommand("start","меню 💗"),BotCommand("clear","очистить 🍵"),BotCommand("remember","запомнить 🫶"),BotCommand("model","модель ✨")],scope=BotCommandScopeAllPrivateChats())
    except: pass
def main():
    start_health_server()
    import time
    while True:
        try:
            app=Application.builder().token(BOT_TOKEN).post_init(set_private_commands).build()
            app.add_handler(CommandHandler("start",start))
            app.add_handler(CommandHandler("help",help_cmd))
            app.add_handler(CommandHandler("about",about_cmd))
            app.add_handler(CommandHandler("clear",clear))
            app.add_handler(CommandHandler("remember",remember_cmd))
            app.add_handler(CommandHandler("model",model_info))
            app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS,welcome_group))
            app.add_handler(MessageHandler(filters.Sticker.ALL,handle_sticker))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_message))
            print(f"Airy {GEMINI_MODEL}")
            app.run_polling(allowed_updates=Update.ALL_TYPES,drop_pending_updates=True)
        except Exception as e:
            logger.error(f"crash {e}"); time.sleep(5)
if __name__=="__main__": main()
