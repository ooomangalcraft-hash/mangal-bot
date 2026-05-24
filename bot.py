"""
bot.py — Mangal Craft Telegram Bot
Render.com (бесплатный тариф) + aiogram 3.x + FastAPI

Архитектура:
  - FastAPI-сервер держит процесс живым (Render требует открытый порт)
  - Polling запускается в отдельном asyncio-task ВНУТРИ того же event loop
  - Единственный процесс гарантируется флагом _polling_started + threading.Lock
  - При старте сбрасывается любой старый webhook и pending updates
"""

import asyncio
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from fastapi import FastAPI

# ─── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mangal_craft")

# ─── Импорт конфига ───────────────────────────────────────────────────────────
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

# ─── Импорт kb_loader ─────────────────────────────────────────────────────────
try:
    from kb_loader import ProductKB
    kb = ProductKB(CSV_PATH)
    logger.info(f"✅ kb_loader.py загружен успешно. Товаров в базе: {len(kb.products)}")
except ImportError as e:
    logger.critical(f"❌ Не могу импортировать kb_loader.py: {e}")
    sys.exit(1)
except Exception as e:
    logger.critical(f"❌ Ошибка инициализации ProductKB: {e}")
    sys.exit(1)

# ─── Защита от двойного запуска polling ──────────────────────────────────────
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
    await message.answer(
        "🔥 <b>Добро пожаловать в Mangal Craft!</b>\n\n"
        "Мы предлагаем шашлычные наборы, шампуры и аксессуары для барбекю.\n\n"
        "💬 <b>Просто напишите что ищете</b>, например:\n"
        "  • <i>шампуры для люля</i>\n"
        "  • <i>мангал складной</i>\n"
        "  • <i>набор для барбекю</i>\n\n"
        "Или напишите <b>оператор</b> — и я подключу специалиста."
    )
    logger.info(f"✅ Приветствие отправлено пользователю {user.id}")


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    logger.info(f"📩 /help от {message.from_user.id}")
    await message.answer(
        "ℹ️ <b>Как пользоваться ботом:</b>\n\n"
        "Просто напишите название товара или категорию — я найду подходящие позиции в каталоге.\n\n"
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

    # ── 1. Проверка на эскалацию ──────────────────────────────────────────────
    lower = text.lower()
    if any(kw in lower for kw in ESCALATION_KEYWORDS):
        logger.info(f"🚨 Эскалация по ключевым словам от пользователя {user.id}")
        await escalate(message, reason="ключевое слово")
        return

    # ── 2. Поиск товаров ──────────────────────────────────────────────────────
    logger.info(f"🔍 Ищу в каталоге: «{text}»")
    try:
        results = kb.search(text, top_k=5)
    except Exception as e:
        logger.error(f"❌ Ошибка поиска: {e}", exc_info=True)
        await message.answer("⚠️ Временная ошибка при поиске. Попробуйте ещё раз.")
        return

    logger.info(f"🔍 Результатов поиска: {len(results)}")

    # ── 3. Нет результатов ────────────────────────────────────────────────────
    if not results:
        logger.info(f"⚠️ Ничего не найдено для: «{text}»")
        await message.answer(
            f"😔 По запросу «<b>{text}</b>» ничего не нашлось.\n\n"
            "Попробуйте другое название или напишите <b>оператор</b> — помогу лично."
        )
        return

    # ── 4. Отправляем результаты ──────────────────────────────────────────────
    response_lines = [f"🛒 <b>Нашёл по запросу «{text}»:</b>\n"]

    for i, item in enumerate(results, 1):
        name = item.get("Title", "Без названия")
        price = item.get("Price", 0)
        description = item.get("Description", "")
        sku = item.get("SKU", "")

        try:
            price_str = f"{int(float(price)):,} ₽".replace(",", " ")
        except (ValueError, TypeError):
            price_str = "цена по запросу"

        block = f"<b>{i}. {name}</b>\n💰 {price_str}"
        if sku:
            block += f"\n🏷️ Арт: {sku}"
        if description:
            desc_short = str(description)[:150] + "…" if len(str(description)) > 150 else str(description)
            block += f"\n📝 {desc_short}"
        response_lines.append(block)

    response_lines.append("\n🔗 <a href='https://mangal-craft.shop'>Весь каталог на сайте</a>")
    response_lines.append("✍️ Уточните запрос или напишите <b>оператор</b> для помощи.")
    response = "\n\n".join(response_lines)

    await message.answer(response)
    logger.info(f"✅ Отправлено {len(results)} товаров пользователю {user.id}")


# ════════════════════════════════════════════════════════════════════════════
# ЭСКАЛАЦИЯ
# ════════════════════════════════════════════════════════════════════════════

async def escalate(message: Message, reason: str = "") -> None:
    user = message.from_user

    await message.answer(
        "👨‍💼 <b>Подключаю специалиста...</b>\n\n"
        "Оператор свяжется с вами в ближайшее время. "
        "Обычно это занимает несколько минут."
    )
    logger.info(f"📤 Эскалация: отправляю уведомление @{ADMIN_USERNAME}")

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
        await bot.send_message(chat_id=f"@{admin_handle}", text=admin_text)
        logger.info(f"✅ Уведомление отправлено @{admin_handle}")
    except Exception as e:
        logger.error(f"❌ Не могу уведомить @{admin_handle}: {e}")


# ════════════════════════════════════════════════════════════════════════════
# POLLING — запускается ОДИН раз
# ════════════════════════════════════════════════════════════════════════════

async def start_polling_once() -> None:
    global _polling_started

    with _polling_lock:
        if _polling_started:
            logger.warning("⚠️ Polling уже запущен — пропускаю повторный старт")
            return
        _polling_started = True

    logger.info("🤖 Инициализация бота...")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook удалён, pending updates сброшены")
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении webhook: {e}")

    await asyncio.sleep(2)

    logger.info("🚀 Запускаю polling...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
            handle_signals=False,
        )
    except asyncio.CancelledError:
        logger.info("⏹️ Polling остановлен (CancelledError)")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка polling: {e}", exc_info=True)
    finally:
        logger.info("🔌 Закрываю сессию бота...")
        await bot.session.close()


# ════════════════════════════════════════════════════════════════════════════
# FASTAPI
# ════════════════════════════════════════════════════════════════════════════

_polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _polling_task
    logger.info("🌐 FastAPI lifespan: запуск")

    _polling_task = asyncio.create_task(start_polling_once(), name="bot_polling")
    logger.info("✅ Задача polling создана")

    yield

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
        workers=1,  # ОБЯЗАТЕЛЬНО — иначе конфликт polling
        log_level="info",
    )
