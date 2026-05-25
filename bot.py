"""
bot.py — Mangal Craft Telegram Bot
Render.com + aiogram 3.x + FastAPI + Claude AI
"""

import asyncio
import logging
import os
import re
import sys
import threading
from contextlib import asynccontextmanager
from collections import defaultdict

import httpx
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
        CSV_PATH,
    )
    logger.info("✅ config.py загружен успешно")
except ImportError as e:
    logger.critical(f"❌ Не могу импортировать config.py: {e}")
    sys.exit(1)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    logger.critical("❌ ANTHROPIC_API_KEY не задан!")
    sys.exit(1)

# ─── Импорт kb_loader ─────────────────────────────────────────────────────────
try:
    from kb_loader import ProductKB
    kb = ProductKB(CSV_PATH)
    logger.info(f"✅ kb_loader.py загружен. Товаров: {len(kb.products)}")
except Exception as e:
    logger.critical(f"❌ Ошибка загрузки ProductKB: {e}")
    sys.exit(1)

# ─── Системный промпт ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Ты — дружелюбный консультант интернет-магазина Mangal Craft (mangal-craft.shop).

✅ ТВОИ ЗАДАЧИ:
- Помогать выбирать шампуры и аксессуары для гриля
- Отвечать просто, понятно, по делу
- Рассказывать о преимуществах товаров
- Отправлять ссылки на сайт для оформления заказа
- Быть полезным, но не навязчивым

❌ ТЫ НЕ ДЕЛАЕШЬ:
- НЕ оформляешь заказы в чате
- НЕ запрашиваешь ФИО, телефон, адрес, город
- НЕ рассчитываешь доставку
- НЕ давишь на клиента

🎯 ГЛАВНАЯ ЦЕЛЬ: Помочь выбрать → отправить ссылку → клиент оформляет на сайте.

СТИЛЬ ОБЩЕНИЯ:
- Общайся как дружелюбный эксперт, используй "ты"
- Эмодзи умеренно: 🍢 🔥 📦 🎁 🚚 🐂 🌳 🔑
- Короткие предложения, без канцелярита
- Если не знаешь — честно говори и направляй на сайт

РАБОТА СО ССЫЛКАМИ:
- Выбрал товар → сразу отправляй ссылку
- После ссылки: "Переходи, там выберешь опции, рассчитаешь доставку и оформишь заказ 😊"
- Не считай доставку — это делает сайт

УНИКАЛЬНОЕ ПРЕИМУЩЕСТВО — ПРОРЕЗЬ В ШАМПУРЕ:
В наших шампурах есть прорезь (паз) внутри лезвия:
✅ Увеличивается площадь контакта с мясом → фиксация надёжнее
✅ Мясо не падает, не прокручивается → можно держать вертикально
✅ Можно брать жидкий фарш, добавлять овощи, сыр, травы

КАТАЛОГ — 12 НАБОРОВ ШАМПУРОВ:
Общие характеристики:
- Материал: нержавейка (№1-11: AISI 304, №12 XXL: AISI 430)
- Толщина: 2 мм (иногда 3 мм)
- Длина: 40–75 см
- Ширина: 17 мм (1000 ₽/шт) или 21 мм (1200 ₽/шт) для №1-3, №6-9
- Мин. заказ: от 6 шт. (№5 — от 2 шт.)
- Ручка не нагревается
- Мытьё: можно в посудомойке

НАБОРЫ:
№1 Классический | SH-0001 | 6 шт | от 6000 ₽ | Базовая прорезь
№2 Универсальный | SH-0013 | 6 шт | от 6000 ₽ | Альтернативная прорезь
№3 Для тандыра | SH-0025 | 6 шт | от 6000 ₽ | Волнистые прорези — ЛУЧШИЙ ДЛЯ ЛЮЛЯ
№4 Компаньон | SH-0037 | 6 шт | от 4800 ₽ | Узкий, для грибов, овощей
№5 Для лаваша | SH-0043 | от 2 шт | от 3000 ₽ | Тройная вилка
№6 Комбо №1+№2 | SH-0052 | 6 шт | от 6000 ₽
№7 Комбо №3+№1 | SH-0064 | 6 шт | от 6000 ₽
№8 Комбо №2+№3 | SH-0076 | 6 шт | от 6000 ₽
№9 Комбо 1+2+3 | SH-0088 | 9 шт | от 9000 ₽ | Полный тест всех видов
№10 Для ресторанов | SH-0102 | 6 шт | от 4800 ₽ | Укороченный
№11 Тандыр с крючками | SH-0108 | 6 шт | от 6000 ₽
№12 XXL | SH-0120 | 6 шт | от 7800 ₽ | ~75 см, AISI 430

ССЫЛКИ НА НАБОРЫ:
№1: https://mangal-craft.shop/product/klassicheskiy/
№2: https://mangal-craft.shop/product/universalnyy/
№3: https://mangal-craft.shop/product/dlya-tandyra/
№4: https://mangal-craft.shop/product/kompanion/
№5: https://mangal-craft.shop/product/dlya-lavasha/
№6-9: https://mangal-craft.shop/product/kombinirovannyy/
№10: https://mangal-craft.shop/product/dlya-restoranov/
№11: https://mangal-craft.shop/product/tandyr-s-kryuchkami/
№12: https://mangal-craft.shop/product/xxl/

ДОП. ТОВАРЫ:
🐂 Голова быка | BULL-0001 | 13000–21000 ₽ | Дерево, ручная работа, 10 шампуров | Отличный подарок!
https://mangal-craft.shop/product/golova-byka/

🌳 Шашлычные деревья (для духовки, тандыра, печи):
№1 Базовое | ST-0001 | 3700–4000 ₽
№2 Двойные вилки | ST-0002 | 3800–4200 ₽
№3 Тройные вилки | ST-0003 | 3900–4300 ₽
№4 Курник | ST-0004 | 3700–4000 ₽
№5 Полный набор (хит!) | ST-0005 | 6800–9000 ₽ | 27 шампуров
https://mangal-craft.shop/product/shashlychnoe-derevo-polnyy-nabor/

🔁 Вертела:
С мотором | VR-0001 | 53000 ₽ | Электропривод 12В
https://mangal-craft.shop/product/vertel-s-motorom/
Ручной | VR-0002 | 15000 ₽
https://mangal-craft.shop/product/vertel-ruchnoy/

FAQ:
- Толщина стали: 2 мм (иногда 3 мм)
- Нержавейка: да, пищевая AISI 304 (№12 — AISI 430)
- Посудомойка: да, но для блеска лучше ручное мытьё
- Ручка нагревается: нет, диффузоры защищают
- Длина: 40–75 см, уточни мангал — подберу
- Деревянная ручка: нет, все цельнометаллические
- Для люля: лучший — №3, волнистые прорези, рекомендуй 21 мм
- 17 или 21 мм: 21 мм надёжнее для люля, 17 мм — классика для шашлыка
- Сроки: до 5 дней по договору, обычно 1–2 дня
- Маркетплейсы: нет, только mangal-craft.shop
- Производство: СПб, доставка по РФ через СДЭК

ЛОГИКА ПОДБОРА:
- Люля/шашлык → №1-3, рекомендовать №3 + 21 мм
- Овощи/мелочь → №4 Компаньон
- Лаваш/много мяса → №5
- Тандыр → №3 или №11
- Кафе/ресторан → №10
- Очень длинные → №12 XXL
- Не могу выбрать → Комбо №6-9
- Подарок → Голова быка + набор ИЛИ дерево №5
- Духовка → Шашлычное дерево
- Баран/поросёнок → Вертел

ДОСТАВКА И ОПЛАТА:
- Только СДЭК, по РФ
- Мин. заказ: 3000 ₽
- Стоимость доставки — на сайте при оформлении
- От 20000 ₽: возможна международная доставка
- Оплата: онлайн картами РФ, юрлицам по счёту
- Контакты: +7 (965) 014-19-28, сайт mangal-craft.shop

ОГРАНИЧЕНИЯ:
1. НЕ запрашивай ФИО, телефон, адрес, город
2. НЕ считай доставку
3. НЕ оформляй заказы в чате
4. НЕ дави на клиента
5. Если не знаешь — направляй в поддержку на сайте
6. Всегда отправляй ссылку после рекомендации
7. Если клиент неадекватен — вежливо завершай и направляй в поддержку

ВАЖНО: Отвечай ТОЛЬКО на русском языке. Не используй Markdown разметку (**, __, ##) — только обычный текст и эмодзи."""

# ─── История диалогов (в памяти) ─────────────────────────────────────────────
# Храним последние 10 сообщений на пользователя
conversation_history: dict[int, list] = defaultdict(list)
MAX_HISTORY = 10

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
# CLAUDE AI
# ════════════════════════════════════════════════════════════════════════════

async def ask_claude(user_id: int, user_message: str) -> str:
    """Отправляет сообщение в Claude API и возвращает ответ."""

    # Добавляем сообщение пользователя в историю
    conversation_history[user_id].append({
        "role": "user",
        "content": user_message
    })

    # Обрезаем историю до MAX_HISTORY сообщений
    if len(conversation_history[user_id]) > MAX_HISTORY:
        conversation_history[user_id] = conversation_history[user_id][-MAX_HISTORY:]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1000,
                    "system": SYSTEM_PROMPT,
                    "messages": conversation_history[user_id],
                }
            )
            response.raise_for_status()
            data = response.json()
            assistant_message = data["content"][0]["text"]

            # Сохраняем ответ ассистента в историю
            conversation_history[user_id].append({
                "role": "assistant",
                "content": assistant_message
            })

            return assistant_message

    except httpx.TimeoutException:
        logger.error(f"❌ Timeout при запросе к Claude API для пользователя {user_id}")
        return "⚠️ Немного задержка — попробуй ещё раз через секунду!"
    except Exception as e:
        logger.error(f"❌ Ошибка Claude API: {e}", exc_info=True)
        return "⚠️ Что-то пошло не так. Попробуй ещё раз или напиши оператору!"


def clean_response(text: str) -> str:
    """Убирает Markdown разметку из ответа Claude."""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'#{1,6}\s', '', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    return text.strip()


# ════════════════════════════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    logger.info(f"📩 /start от {user.full_name} (id={user.id})")

    # Сбрасываем историю при /start
    conversation_history[user.id].clear()

    await message.answer(
        "🔥 Привет! Я консультант магазина Mangal Craft.\n\n"
        "Помогу выбрать шампуры, наборы и аксессуары для гриля 🍢\n\n"
        "Просто напиши что ищешь — например:\n"
        "  • шампуры для люля\n"
        "  • подарок для друга\n"
        "  • что лучше для тандыра\n\n"
        "Или напиши оператор — подключу живого специалиста."
    )
    logger.info(f"✅ Приветствие отправлено {user.id}")


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    logger.info(f"📩 /help от {message.from_user.id}")
    await message.answer(
        "ℹ️ Я помогу выбрать шампуры и аксессуары для гриля.\n\n"
        "Просто напиши что ищешь — отвечу как живой консультант!\n\n"
        "Команды:\n"
        "  /start — начало (сбросит историю диалога)\n"
        "  /help — эта справка\n\n"
        "Для связи с оператором напиши: оператор"
    )


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    user = message.from_user
    text = message.text.strip()
    logger.info(f"📩 !!! СООБЩЕНИЕ от {user.full_name} (id={user.id}): «{text}»")

    # ── 1. Проверка на эскалацию ──────────────────────────────────────────────
    lower = text.lower()
    if any(kw in lower for kw in ESCALATION_KEYWORDS):
        logger.info(f"🚨 Эскалация от пользователя {user.id}")
        await escalate(message, reason="ключевое слово")
        return

    # ── 2. Индикатор набора ───────────────────────────────────────────────────
    await bot.send_chat_action(message.chat.id, "typing")

    # ── 3. Запрос к Claude ────────────────────────────────────────────────────
    logger.info(f"🤖 Запрос к Claude для пользователя {user.id}")
    response = await ask_claude(user.id, text)
    response = clean_response(response)

    logger.info(f"✅ Ответ Claude получен для пользователя {user.id}")
    await message.answer(response)


# ════════════════════════════════════════════════════════════════════════════
# ЭСКАЛАЦИЯ
# ════════════════════════════════════════════════════════════════════════════

async def escalate(message: Message, reason: str = "") -> None:
    user = message.from_user

    await message.answer(
        "👨‍💼 Подключаю специалиста...\n\n"
        "Оператор свяжется с тобой в ближайшее время 😊"
    )
    logger.info(f"📤 Эскалация → @{ADMIN_USERNAME}")

    admin_handle = ADMIN_USERNAME.lstrip("@")
    admin_text = (
        f"🚨 <b>Запрос к оператору</b>\n\n"
        f"👤 {user.full_name}"
        + (f" (@{user.username})" if user.username else "")
        + f"\n🆔 <code>{user.id}</code>\n"
        f"💬 «{message.text}»\n"
        f"📌 Причина: {reason}"
    )

    try:
        await bot.send_message(chat_id=f"@{admin_handle}", text=admin_text)
        logger.info(f"✅ Уведомление отправлено @{admin_handle}")
    except Exception as e:
        logger.error(f"❌ Не могу уведомить @{admin_handle}: {e}")


# ════════════════════════════════════════════════════════════════════════════
# POLLING
# ════════════════════════════════════════════════════════════════════════════

async def start_polling_once() -> None:
    global _polling_started

    with _polling_lock:
        if _polling_started:
            logger.warning("⚠️ Polling уже запущен")
            return
        _polling_started = True

    logger.info("🤖 Инициализация бота...")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook удалён")
    except Exception as e:
        logger.error(f"❌ Ошибка webhook: {e}")

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
        logger.info("⏹️ Polling остановлен")
    except Exception as e:
        logger.error(f"💥 Ошибка polling: {e}", exc_info=True)
    finally:
        logger.info("🔌 Закрываю сессию...")
        await bot.session.close()


# ════════════════════════════════════════════════════════════════════════════
# FASTAPI
# ════════════════════════════════════════════════════════════════════════════

_polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _polling_task
    logger.info("🌐 FastAPI запуск")
    _polling_task = asyncio.create_task(start_polling_once(), name="bot_polling")
    yield
    logger.info("🌐 FastAPI завершение")
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
    logger.info(f"🌐 Запуск на порту {port}")
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        log_level="info",
    )
