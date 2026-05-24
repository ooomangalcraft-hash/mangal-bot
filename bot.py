import logging
import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from config import BOT_TOKEN, ADMIN_USERNAME, ESCALATION_KEYWORDS, CONFIDENCE_THRESHOLD, CSV_PATH
from kb_loader import ProductKB
from fastapi import FastAPI
import uvicorn

# Настройка логирования
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы знаний
try:
    kb = ProductKB(CSV_PATH)
    logging.info(f"✅ База знаний загружена. Товаров: {len(kb.products)}")
except Exception as e:
    logging.error(f"❌ Ошибка загрузки базы: {e}")
    kb = None

def calculate_confidence(query: str, results: list) -> float:
    if not results or kb is None:
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

# === ОБРАБОТЧИКИ ===

# 1. Обработчик ТОЛЬКО команды /start
@dp.message(CommandStart)
async def cmd_start(message: types.Message):
    logging.info(f"🚀 Команда /start от {message.from_user.id}")
    await message.answer(
        "👋 Привет! Я бот-помощник 🔥 Mangal Craft.\n\n"
        "Спрашивайте про шампуры, шашлычные деревья и вертела\n\n"
        "Например:\n"
        "• Какие шампуры для люля?\n"
        "• Цена шашлычного дерева?\n\n"
        "Если не найду ответ — подключу оператора 👨‍🔧",
        parse_mode="Markdown"
    )

# 2. Обработчик ЛЮБОГО текста (кроме команд)
@dp.message(F.text)
async def handle_message(message: types.Message):
    if kb is None:
        logging.error("❌ База знаний НЕ загружена!")
        await message.answer("⚠️ Ошибка: база знаний не загружена.")
        return

    user_query = message.text.strip()
    logging.info(f"💬 Текст от {message.from_user.id}: {user_query}")
    
    # Поиск
    try:
        results = kb.search(user_query, top_k=3)
        confidence = calculate_confidence(user_query, results)
        logging.info(f"🔍 Найдено {len(results)} товаров, уверенность: {confidence:.2f}")
    except Exception as e:
        logging.error(f"❌ Ошибка поиска: {e}")
        await message.answer("❌ Ошибка при поиске.")
        return
    
    # Эскалация
    if needs_escalation(user_query, confidence):
        user_info = f"@{message.from_user.username}" if message.from_user.username else f"{message.from_user.first_name}"
        logging.info(f"🔔 Эскалация: {user_query}")
        try:
            await bot.send_message(
                chat_id=ADMIN_USERNAME,
                text=f"🔔 *Запрос*\n👤 {user_info}\n❓ {user_query}",
                parse_mode="Markdown"
            )
            await message.answer("👨‍🔧 Подключаю оператора...")
        except Exception as e:
            logging.error(f"❌ Ошибка уведомления: {e}")
        return
    
    # Результат
    if results:
        answer = "🔍 Нашёл:\n\n"
        for p in results:
            answer += kb.format_product(p) + "\n\n"
        await message.answer(answer, parse_mode="Markdown")
    else:
        await message.answer("🤔 Не нашёл. Напишите «оператор».")

# === FastAPI ===
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "products": len(kb.products) if kb else 0}

# === Запуск ===
async def start_bot():
    logging.info("🚀 Запуск...")
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    import threading
    
    def run_server():
        port = int(os.getenv("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port)
    
    threading.Thread(target=run_server, daemon=True).start()
    asyncio.run(start_bot())
