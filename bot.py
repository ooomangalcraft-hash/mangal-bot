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

@dp.message(CommandStart)
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    logging.info(f"🚀 /start от {message.from_user.id}")
    await message.answer(
        "👋 Привет! Я бот-помощник 🔥 Mangal Craft.\n\n"
        "Спрашивайте про шампуры, шашлычные деревья и вертела\n\n"
        "Например:\n"
        "• Какие шампуры для люля?\n"
        "• Цена шашлычного дерева?\n\n"
        "Если не найду ответ — подключу оператора 👨‍🔧",
        parse_mode="Markdown"
    )

@dp.message(F.text)
async def handle_text(message: types.Message):
    """Обработчик всех текстовых сообщений"""
    if kb is None:
        await message.answer("⚠️ Ошибка: база знаний не загружена.")
        return

    user_query = message.text.strip()
    logging.info(f"💬 Вопрос от {message.from_user.id}: {user_query}")
    
    # Поиск в базе
    try:
        results = kb.search(user_query, top_k=3)
        confidence = calculate_confidence(user_query, results)
    except Exception as e:
        logging.error(f"❌ Ошибка поиска: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")
        return
    
    # Проверка на эскалацию (оператор / низкая уверенность)
    if needs_escalation(user_query, confidence):
        user_info = f"@{message.from_user.username}" if message.from_user.username else f"{message.from_user.first_name}"
        logging.info(f"🔔 Эскалация: {user_query}")
        try:
            await bot.send_message(
                chat_id=ADMIN_USERNAME,
                text=f"🔔 *Запрос на оператора*\n👤 Клиент: {user_info}\n❓ Вопрос: {user_query}\n🤖 Уверенность: {confidence:.2f}",
                parse_mode="Markdown"
            )
            await message.answer("👨‍🔧 Сейчас подключу специалиста! Ожидайте.", reply_to_message_id=message.message_id)
        except Exception as e:
            logging.error(f"❌ Не удалось уведомить админа: {e}")
            await message.answer("⚠️ Не удалось связаться с оператором. Напишите @SVKolosov")
        return
    
    # Ответ с товарами
    if results:
        answer = "🔍 Нашёл варианты:\n\n"
        for p in results:
            answer += kb.format_product(p) + "\n\n"
        await message.answer(answer, parse_mode="Markdown")
    else:
        await message.answer(
            "🤔 Пока не нашёл точного ответа.\n"
            "Попробуйте переформулировать или напишите «оператор».",
            reply_to_message_id=message.message_id
        )

# === FastAPI (веб-сервер для Render) ===
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "bot": "Mangal Craft Bot is running", "products": len(kb.products) if kb else 0}

@app.get("/health")
async def health():
    return {"status": "alive"}

# === Запуск ===
async def start_bot():
    logging.info("🚀 Запуск polling...")
    # drop_pending_updates=True — критически важно для избежания конфликтов!
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    import threading
    
    # Веб-сервер в фоновом потоке
    def run_server():
        port = int(os.getenv("PORT", 8000))
        logging.info(f"🌐 Веб-сервер на порту {port}")
        uvicorn.run(app, host="0.0.0.0", port=port)
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Бот в главном потоке
    asyncio.run(start_bot())
