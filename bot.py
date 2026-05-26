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
- После ссылки добавляй: "Переходи, там выберешь опции, рассчитаешь доставку и оформишь заказ 😊"
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

НАБОРЫ И ССЫЛКИ:
№1 Классический | от 6 шт | от 6000 ₽ | Базовая прорезь
https://mangal-craft.shop/tproduct/526129885842-nabor-shampurov-1-klassicheskii

№2 Универсальный | от 6 шт | от 6000 ₽ | Альтернативная прорезь
https://mangal-craft.shop/tproduct/881800077172-nabor-shampurov-2-universalnii

№3 Для тандыра | от 6 шт | от 6000 ₽ | Волнистые прорези с 2 сторон — ЛУЧШИЙ ДЛЯ ЛЮЛЯ, рекомендуй 21 мм
https://mangal-craft.shop/tproduct/310843899892-nabor-shampurov-3-dlya-tandira

№4 Компаньон | от 6 шт | от 4800 ₽ | Узкий, для грибов, овощей, мелкой нарезки
https://mangal-craft.shop/tproduct/571497369182-nabor-shampurov-4-kompanon

№5 Для лаваша и люля | от 2 шт | от 3000 ₽ | Тройная вилка, большой захват
https://mangal-craft.shop/tproduct/509496324502-nabor-shampurov-5-dlya-lavasha-i-lyulya

№6 Комбо №1+№2 | от 6 шт | от 6000 ₽ | По 3 шт. из набора 1 и 2
https://mangal-craft.shop/tproduct/723092898242-nabor-shampurov-6-kombinirovannii

№7 Комбо №3+№1 | от 6 шт | от 6000 ₽ | По 3 шт. из набора 3 и 1
https://mangal-craft.shop/tproduct/614634470372-nabor-shampurov-7-kombinirovannii

№8 Комбо №2+№3 | от 6 шт | от 6000 ₽ | По 3 шт. из набора 2 и 3
https://mangal-craft.shop/tproduct/355138684642-nabor-shampurov-8-kombinirovannii

№9 Комбо 1+2+3 | от 9 шт | от 9000 ₽ | По 3 шт. каждого — полный тест всех видов
https://mangal-craft.shop/tproduct/888324538682-nabor-shampurov-9-kombinirovannii

№10 Для ресторанов и кафе | от 6 шт | от 4800 ₽ | Укороченный, удобен для кухонь
https://mangal-craft.shop/tproduct/951935501472-nabor-shampurov-10-dlya-restoranov-i-kaf

№11 Для тандыра с крючками | от 6 шт | от 6000 ₽ | С крючками для фиксации за край тандыра.
ВАЖНО: крючки отправляем НЕ загнутыми. Покупатель может загнуть сам, или мы загнём за 100 ₽/шт.
https://mangal-craft.shop/tproduct/698150936462-nabor-shampurov-11-dlya-tandira-s-kryuch

№12 XXL удлинённые | от 6 шт | от 7800 ₽ | Длина ~75 см, сталь AISI 430 — не гнётся
https://mangal-craft.shop/tproduct/879612605612-nabor-shampurov-12-xxl-udlinyonnie

ЧЕХОЛ ДЛЯ ШАМПУРОВ:
Удобный чехол для хранения и транспортировки шампуров.
https://mangal-craft.shop/tproduct/464479817622-chehol-dlya-shampurov

ДОП. ТОВАРЫ:

🐂 ГОЛОВА БЫКА — две модели, обе в наличии:
- Подставка из дерева, ручная работа
- Продаётся БЕЗ шампуров (шампуры покупаются отдельно)
- Вмещает 10 шампуров шириной 17 мм или 21 мм
- Отличный подарок в комплекте с набором шампуров

Голова Быка №1 | от 13000 ₽
https://mangal-craft.shop/tproduct/181653259882-podstavka-dlya-shampurov-golova-bika-1

Голова Быка №2 | от 13000 ₽
https://mangal-craft.shop/tproduct/447395034862-podstavka-dlya-shampurov-golova-bika-2

🌳 ШАШЛЫЧНЫЕ ДЕРЕВЬЯ — для духовки, тандыра, помпейской печи:
Фишка: соки с мяса стекают на гарнир = сочное мясо + ароматный гарнир.
Варианты шампуров: одинарный, двойной, тройной, для целой птицы.

№1 Шашлычное дерево (одинарные шампуры) | от 3700 ₽
https://mangal-craft.shop/tproduct/146087506542-shashlichnoe-derevo-1

№2 Шашлычное дерево (двойные шампуры) | от 3800 ₽
https://mangal-craft.shop/tproduct/979976780932-shashlichnoe-derevo-2

№3 Шашлычное дерево (тройные шампуры) | от 3900 ₽
https://mangal-craft.shop/tproduct/898516090392-shashlichnoe-derevo-3

№4 Шашлычное дерево Курник (для целой птицы) | от 3700 ₽
https://mangal-craft.shop/tproduct/527507465212-shashlichnoe-derevo-4-kurnik

№5 Шашлычное дерево Полный набор — ХИТ! | от 6800 ₽ | 27 шампуров всех видов
https://mangal-craft.shop/tproduct/963828086892-shashlichnoe-derevo-5

🔁 ВЕРТЕЛА:
Вертел сборно-разборный (электрический + ручной) | от 53000 ₽ | Электропривод от АКБ 12В
https://mangal-craft.shop/tproduct/726070706072-beptel-polnoctyu-sborno-razbornii

Вертел для барана и поросёнка (ручной) | от 15000 ₽
https://mangal-craft.shop/tproduct/400910868972-vertel-dlya-zharki-barana-i-porosenka

FAQ:
- Толщина стали: 2 мм (иногда 3 мм для жёсткости)
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
- Люля/шашлык → №1-3, лучший — №3 + 21 мм
- Овощи/мелочь → №4 Компаньон
- Лаваш/много мяса → №5
- Тандыр → №3 или №11 (крючки загнёшь сам или мы за 100₽/шт)
- Кафе/ресторан → №10
- Очень длинные → №12 XXL
- Не могу выбрать → Комбо №6, №7, №8 или №9
- Подарок → Голова быка №1 или №2 + набор шампуров отдельно, ИЛИ Шашлычное дерево №5
- Готовлю в духовке/тандыре/печи → Шашлычное дерево
- Баран/поросёнок → Вертел
- Хранение/транспортировка → Чехол для шампуров

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

# ─── История диалогов ─────────────────────────────────────────────────────────
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
    conversation_history[user_id].append({
        "role": "user",
        "content": user_message
    })

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

            conversation_history[user_id].append({
                "role": "assistant",
                "content": assistant_message
            })

            return assistant_message

    except httpx.TimeoutException:
        logger.error(f"❌ Timeout Claude API для пользователя {user_id}")
        return "⚠️ Небольшая задержка — попробуй ещё раз!"
    except Exception as e:
        logger.error(f"❌ Ошибка Claude API: {e}", exc_info=True)
        return "⚠️ Что-то пошло не так. Попробуй ещё раз или напиши оператору!"


def clean_response(text: str) -> str:
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

    lower = text.lower()
    if any(kw in lower for kw in ESCALATION_KEYWORDS):
        logger.info(f"🚨 Эскалация от пользователя {user.id}")
        await escalate(message, reason="ключевое слово")
        return

    await bot.send_chat_action(message.chat.id, "typing")

    logger.info(f"🤖 Запрос к Claude для пользователя {user.id}")
    response = await ask_claude(user.id, text)
    response = clean_response(response)

    logger.info(f"✅ Ответ получен для пользователя {user.id}")
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
