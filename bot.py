"""
bot.py — Mangal Craft Telegram Bot
Render.com (бесплатный тариф) + aiogram 3.x + FastAPI

Архитектура:
  - FastAPI-сервер держит процесс живым (Render требует открытый порт)
  - Polling запускается в отдельном asyncio-task ВНУТРИ того же event loop
  - Единственный процесс гарантируется флагом _BOT_STARTED + asyncio.Event
  - При старте сбрасывается любой старый webhook и pending updates
"""

import asyncio
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from fastapi import FastAPI

# ─── Логирование ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mangal_craft")

# ─── Импорт конфига и kb_loader ──────────────────────────────────────────────
try:
    from config import (
        BOT_TOKEN,
        ADMIN_USERNAME,
        ESCALATION_KEYWORDS,
        CONFIDENCE_THRESHOLD,
        CSV_PATH,
    )
    logger.info("✅ config.py загружен успешно")
except ImportError as e:
    logger.critical(f"❌ Не могу импортировать config.py: {e}")
    sys.exit(1)

try:
    from kb_loader import search_products  # возвращает list[dict] с полями name/price/description/score
    logger.info("✅ kb_loader.py загружен успешно")
except ImportError as e:
    logger.critical(f"❌ Не могу импортировать kb_loader.py: {e}")
    sys.exit(1)

# ─── Глобальный флаг: не допускаем двойного старта polling ──────────────────
_polling_started = False
_polling_lock = threading.Lock()

# ─── Инициализация бота и диспетчера ─────────────────────────────────────────
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# ════════════════════════════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    logger.info(f"📩 /start от {user.full_name} (id={user.id})")

    text = (
        "🔥 <b>Добро пожаловать в Mangal Craft!</b>\n\n"
        "Мы предлагаем шашлычные наборы, шампуры и аксессуары для барбекю.\n\n"
        "💬 <b>Просто напишите что ищете</b>, например:\n"
        "  • <i>шампуры для люля</i>\n"
        "  • <i>мангал складной</i>\n"
        "  • <i>набор для барбекю</i>\n\n"
        "Или напишите <b>оператор</b> — и я подключу специалиста."
    )
    await message.answer(text)
    logger.info(f"✅ Приветствие отправлено пользователю {user.id}")


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    logger.info(f"📩 /help от {message.from_user.id}")
    await message.answer(
        "ℹ️ <b>Как пользоваться ботом:</b>\n\n"
        "Просто напишите название товара или категорию — я найду подходящие позиции в нашем каталоге.\n\n"
        "Команды:\n"
        "  /start — начало работы\n"
        "  /help — эта справка\n\n"
        "Для связи с оператором напишите: <b>оператор</b>"
    )


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    user = message.from_user
    text = message.text.strip()
    logger.info(f"📩 !!! СООБЩЕНИЕ от {user.full_name} (id={user.id}): «{text}»")

    # ── 1. Проверка на эскалацию ─────────────────────────────────────────────
    lower = text.lower()
    if any(kw in lower for kw in ESCALATION_KEYWORDS):
        logger.info(f"🚨 Эскалация по ключевым словам от пользователя {user.id}")
        await escalate(message, reason="ключевое слово")
        return

    # ── 2. Поиск товаров ─────────────────────────────────────────────────────
    logger.info(f"🔍 Ищу в каталоге: «{text}»")
    try:
        results = search_products(text)
    except Exception as e:
        logger.error(f"❌ Ошибка поиска: {e}", exc_info=True)
        await message.answer("⚠️ Временная ошибка при поиске. Попробуйте ещё раз.")
        return

    logger.info(f"🔍 Результатов поиска: {len(results)}")

    # ── 3. Нет результатов или низкая уверенность ────────────────────────────
    if not results:
        logger.info(f"⚠️ Ничего не найдено для: «{text}»")
        await message.answer(
            f"😔 По запросу «<b>{text}</b>» ничего не нашлось.\n\n"
            "Попробуйте другое название или напишите <b>оператор</b> — помогу лично."
        )
        return

    # Проверяем confidence первого (лучшего) результата
    best_score = results[0].get("score", 1.0)
    logger.info(f"📊 Лучший score: {best_score:.2f} (порог: {CONFIDENCE_THRESHOLD})")

    if best_score < CONFIDENCE_THRESHOLD:
        logger.info(f"⚠️ Низкая уверенность ({best_score:.2f}) — эскалация")
        await escalate(message, reason=f"низкая уверенность ({best_score:.2f})")
        return

    # ── 4. Отправляем результаты ─────────────────────────────────────────────
    response_lines = [f"🛒 <b>Нашёл по запросу «{text}»:</b>\n"]

    for i, item in enumerate(results[:5], 1):
        name = item.get("name", "Без названия")
        price = item.get("price", "—")
        description = item.get("description", "")

        # Форматируем цену
        if isinstance(price, (int, float)):
            price_str = f"{price:,.0f} ₽".replace(",", " ")
        else:
            price_str = str(price)

        block = f"<b>{i}. {name}</b>\n💰 {price_str}"
        if description:
            # Обрезаем длинное описание
            desc_short = description[:150] + "…" if len(description) > 150 else description
            block += f"\n{desc_short}"
        response_lines.append(block)

    response_lines.append("\n✍️ Напишите название товара точнее или задайте вопрос оператору.")
    response = "\n\n".join(response_lines)

    await message.answer(response)
    logger.info(f"✅ Отправлено {len(results[:5])} товаров пользователю {user.id}")


# ════════════════════════════════════════════════════════════════════════════
# ЭСКАЛАЦИЯ
# ════════════════════════════════════════════════════════════════════════════

async def escalate(message: Message, reason: str = "") -> None:
    """Уведомляет пользователя и отправляет уведомление администратору."""
    user = message.from_user

    # Сообщение пользователю
    await message.answer(
        "👨‍💼 <b>Подключаю специалиста...</b>\n\n"
        "Оператор свяжется с вами в ближайшее время. "
        "Обычно это занимает несколько минут."
    )
    logger.info(f"📤 Эскалация: отправляю уведомление @{ADMIN_USERNAME}")

    # Уведомление администратору
    admin_handle = ADMIN_USERNAME.lstrip("@")
    admin_text = (
        f"🚨 <b>Новый запрос к оператору</b>\n\n"
        f"👤 Пользователь: {user.full_name}"
        + (f" (@{user.username})" if user.username else "")
        + f"\n🆔 ID: <code>{user.id}</code>\n"
        f"💬 Сообщение: «{message.text}»\n"
        f"📌 Причина: {reason}\n\n"
        f"➡️ Ответьте пользователю в Telegram."
    )

    try:
        await bot.send_message(
            chat_id=f"@{admin_handle}",
            text=admin_text,
        )
        logger.info(f"✅ Уведомление отправлено @{admin_handle}")
    except Exception as e:
        logger.error(f"❌ Не могу уведомить @{admin_handle}: {e}")
        # Не падаем — пользователь уже получил ответ


# ════════════════════════════════════════════════════════════════════════════
# POLLING — запускается ОДИН раз
# ════════════════════════════════════════════════════════════════════════════

async def start_polling_once() -> None:
    """
    Запускает polling. Использует глобальный флаг чтобы гарантировать
    единственный запуск даже если lifespan вызывается несколько раз.
    """
    global _polling_started

    with _polling_lock:
        if _polling_started:
            logger.warning("⚠️ Polling уже запущен — пропускаю повторный старт")
            return
        _polling_started = True

    logger.info("🤖 Инициализация бота...")

    # Сбрасываем webhook (важно! иначе polling не работает если был webhook)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook удалён, pending updates сброшены")
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении webhook: {e}")

    # Небольшая пауза чтобы Telegram успел закрыть старые соединения
    await asyncio.sleep(2)

    logger.info("🚀 Запускаю polling...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
            handle_signals=False,   # НЕ перехватываем сигналы — это делает uvicorn
        )
    except asyncio.CancelledError:
        logger.info("⏹️ Polling остановлен (CancelledError)")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка polling: {e}", exc_info=True)
    finally:
        logger.info("🔌 Закрываю сессию бота...")
        await bot.session.close()


# ════════════════════════════════════════════════════════════════════════════
# FASTAPI — держит процесс живым на Render
# ════════════════════════════════════════════════════════════════════════════

_polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Запускает polling при старте FastAPI и останавливает при завершении."""
    global _polling_task
    logger.info("🌐 FastAPI lifespan: запуск")

    # Запускаем polling как фоновый task
    _polling_task = asyncio.create_task(start_polling_once(), name="bot_polling")
    logger.info("✅ Задача polling создана")

    yield  # сервер работает

    # Завершение
    logger.info("🌐 FastAPI lifespan: завершение")
    if _polling_task and not _polling_task.done():
        _polling_task.cancel()
        try:
            await asyncio.wait_for(_polling_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    logger.info("👋 Бот остановлен")


app = FastAPI(title="Mangal Craft Bot", lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok", "service": "Mangal Craft Bot"}


@app.get("/health")
async def health():
    """Render пингует этот endpoint — отвечаем 200 чтобы не усыплял сервис."""
    polling_alive = _polling_task is not None and not _polling_task.done()
    return {
        "status": "healthy",
        "polling": "running" if polling_alive else "stopped",
    }


# ════════════════════════════════════════════════════════════════════════════
# ТОЧКА ВХОДА
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🌐 Запуск uvicorn на порту {port}")
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=port,
        # workers=1 — ОБЯЗАТЕЛЬНО! Иначе несколько worker-процессов = конфликт
        workers=1,
        log_level="info",
    )
