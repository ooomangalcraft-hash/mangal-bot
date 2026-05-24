import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from config import BOT_TOKEN, ADMIN_USERNAME, ESCALATION_KEYWORDS, CONFIDENCE_THRESHOLD, CSV_PATH
from kb_loader import ProductKB
from fastapi import FastAPI
import uvicorn

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
kb = ProductKB(CSV_PATH)

def calculate_confidence(query: str, results: list) -> float:
    if not results: 
        return 0.0
    q_words = set(kb.normalize(query).split())
    best = results[0]
    title = kb.normalize(best.get('Title', ''))
    matches = len(q_words & set(title.split()))
    return min(1.0, matches / max(1, len(q_words)))

def needs_escalation(query: str, confidence: float) -> bool:
    query_lower = query.lower()
    if any(kw in query_lower for kw in ESCALATION_KEYWORDS): 
        return True
    if confidence < CONFIDENCE_THRESHOLD: 
        return True
    return False

@dp.message(CommandStart)
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот-помощник *Mangal Craft*.\n\n"
        "Спрашивайте про шампуры, деревья, вертела и аксессуары.\n"
        "Примеры:\n• Какие шампуры для люля?\n• Есть чехлы?\n• Цена дерева №3?\n\n"
        "Если не найду ответ — подключу оператора 👨‍🔧",
        parse_mode="Markdown"
    )

@dp.message()
async def handle_message(message: types.Message):
    user_query = message.text
    user_info = f"@{message.from_user.username}" if message.from_user.username else f"{message.from_user.first_name} (ID:{message.from_user.id})"
    
    results = kb.search(user_query, top_k=3)
    confidence = calculate_confidence(user_query, results)
    
    if needs_escalation(user_query, confidence):
        try:
            await bot.send_message(
                chat_id=ADMIN_USERNAME,
                text=f"🔔 *Запрос на оператора*\n👤 Клиент: {user_info}\n❓ Вопрос: {user_query}\n🤖 Уверенность: {confidence:.2f}",
                parse_mode="Markdown"
            )
            await message.answer("👨‍🔧 Сейчас подключу специалиста! Ожидайте, он ответит в ближайшее время.", reply_to_message_id=message.message_id)
        except Exception as e:
            logging.error(f"Failed to notify admin: {e}")
            await message.answer("⚠️ Не удалось связаться с оператором. Напишите напрямую @SVKolosov")
        return
    
    if results:
        answer = "🔍 Нашёл варианты:\n\n"
        for p in results:
            answer += kb.format_product(p) + "\n\n"
        await message.answer(answer, parse_mode="Markdown")
    else:
        await message.answer("🤔 Пока не нашёл точного ответа. Переформулируйте или напишите «оператор».", reply_to_message_id=message.message_id)

app = FastAPI()

@app.get("/")
async def health():
    return {"status": "ok", "bot": "running"}

@app.get("/webhook")
async def webhook():
    return {"status": "alive"}

async def start_bot():
    await dp.start_polling(bot)

def run_bot():
    import asyncio
    asyncio.run(start_bot())

if __name__ == "__main__":
    import threading
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))