"""
bot.py — Mangal Craft Telegram Bot + Web Widget API
Render.com + aiogram 3.x + FastAPI + Claude AI
"""

import asyncio
import logging
import os
import re
import sys
import threading
import uuid
import time
from contextlib import asynccontextmanager
from collections import defaultdict

import httpx
import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

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

# ─── ID оператора ─────────────────────────────────────────────────────────────
OPERATOR_TELEGRAM_ID = 684062021  # Сергей @SVKolosov

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

КОНТАКТЫ ДЛЯ ПОДДЕРЖКИ:
- Телеграм: @SVKolosov (Сергей)
- Телефон: +7 (965) 014-19-28 (Владимир)
- НЕ отправляй на форму обратной связи сайта — только телеграм или телефон!

ИНДИВИДУАЛЬНОЕ ИЗГОТОВЛЕНИЕ:
- Возможно изготовление шампуров по индивидуальным размерам!
- Для этого направляй звонить: +7 (965) 014-19-28 (Владимир)

СТИЛЬ ОБЩЕНИЯ:
- Общайся как дружелюбный эксперт, используй "ты"
- Эмодзи умеренно: 🍢 🔥 📦 🎁 🚚 🐂 🌳 🔑
- Короткие предложения, без канцелярита
- Если не знаешь — честно говори и направляй к @SVKolosov или +7 (965) 014-19-28

РАБОТА СО ССЫЛКАМИ:
- Выбрал товар → сразу отправляй ссылку
- После ссылки: "Переходи, там выберешь опции, рассчитаешь доставку и оформишь заказ 😊"
- Не считай доставку — это делает сайт

УНИКАЛЬНОЕ ПРЕИМУЩЕСТВО — ПРОРЕЗЬ В ШАМПУРЕ:
В наших шампурах есть прорезь (паз) внутри лезвия:
✅ Увеличивается площадь контакта с мясом → фиксация надёжнее
✅ Мясо не падает, не прокручивается → можно держать вертикально
✅ Можно брать жидкий фарш, добавлять овощи, сыр, травы
✅ Подходит для рыбных стейков — жарятся как обычный шашлык
✅ В фарш можно добавлять измельчённые морепродукты — держится даже жидкий фарш

РЕШЁТКА ИЗ ШАМПУРОВ (в разработке):
Несколько шампуров соединяются специальным приспособлением в решётку для жарки рыбы.

КАТАЛОГ — 12 НАБОРОВ ШАМПУРОВ:

№1 Классический | от 6 шт | от 6000 ₽ | Базовая прорезь
Размеры: общая длина 65 см, рабочая поверхность 45 см, ширина 17 или 21 мм, ручка не греется
https://mangal-craft.shop/tproduct/526129885842-nabor-shampurov-1-klassicheskii

№2 Универсальный | от 6 шт | от 6000 ₽ | Альтернативная прорезь
Размеры: общая длина 65 см, рабочая поверхность 45 см, ширина 17 или 21 мм, ручка не греется
https://mangal-craft.shop/tproduct/881800077172-nabor-shampurov-2-universalnii

№3 Для тандыра | от 6 шт | от 6000 ₽ | Волнистые прорези с 2 сторон — ЛУЧШИЙ ДЛЯ ЛЮЛЯ, рекомендуй 21 мм
Размеры: общая длина 65 см, рабочая поверхность 45 см, ширина 17 или 21 мм, ручка не греется
https://mangal-craft.shop/tproduct/310843899892-nabor-shampurov-3-dlya-tandira

№4 Компаньон | от 6 шт | от 4800 ₽ | Узкий, для грибов, овощей, мелкой нарезки. НЕ комбинируется с другими наборами!
Размеры: общая длина 55 см, рабочая поверхность 40 см, ширина 6 мм, ручка не греется
https://mangal-craft.shop/tproduct/571497369182-nabor-shampurov-4-kompanon

№5 Для лаваша и люля | от 2 шт | от 3000 ₽ | Тройная вилка, большой захват
Размеры: длина 65 см, ширина 30 см, рабочая поверхность 45 см, толщина 2 мм, ручка не греется
https://mangal-craft.shop/tproduct/509496324502-nabor-shampurov-5-dlya-lavasha-i-lyulya

№6 Комбо №1+№2 | от 6 шт | от 6000 ₽ | По 3 шт. из набора №1 и №2
https://mangal-craft.shop/tproduct/723092898242-nabor-shampurov-6-kombinirovannii

№7 Комбо №1+№3 | от 6 шт | от 6000 ₽ | По 3 шт. из набора №1 и №3
https://mangal-craft.shop/tproduct/614634470372-nabor-shampurov-7-kombinirovannii

№8 Комбо №2+№3 | от 6 шт | от 6000 ₽ | По 3 шт. из набора №2 и №3
https://mangal-craft.shop/tproduct/355138684642-nabor-shampurov-8-kombinirovannii

№9 Комбо №1+№2+№3 | от 9 шт | от 9000 ₽ | По 3 шт. из наборов №1, №2 и №3
https://mangal-craft.shop/tproduct/888324538682-nabor-shampurov-9-kombinirovannii

№10 Для ресторанов и кафе | от 6 шт | от 4800 ₽ | Только ширина 17 мм
Размеры: общая длина 40 см, рабочая поверхность 30 см, ручка греется незначительно
https://mangal-craft.shop/tproduct/951935501472-nabor-shampurov-10-dlya-restoranov-i-kaf

№11 Для тандыра с крючками | от 6 шт | от 6000 ₽ | Только ширина 21 мм
ВАЖНО: крючки отправляем НЕ загнутыми. Загнуть можно самому или мы за 100 ₽/шт.
Размеры: общая длина 50 см, рабочая поверхность 40 см, ручка греется незначительно
https://mangal-craft.shop/tproduct/698150936462-nabor-shampurov-11-dlya-tandira-s-kryuch

№12 XXL удлинённые | от 6 шт | от 7800 ₽ | Только ширина 21 мм. Сталь AISI 430.
Размеры: общая длина 75 см, рабочая поверхность 55 см, ручка НЕ греется
https://mangal-craft.shop/tproduct/879612605612-nabor-shampurov-12-xxl-udlinyonnie

ЧЕХОЛ ДЛЯ ШАМПУРОВ:
https://mangal-craft.shop/tproduct/464479817622-chehol-dlya-shampurov

ДОП. ТОВАРЫ:

🐂 ГОЛОВА БЫКА — две модели, обе в наличии:
- Подставка из дерева, ручная работа
- Продаётся БЕЗ шампуров (шампуры покупаются отдельно)
- Вмещает 10 шампуров шириной 17 мм или 21 мм
- Подходит к наборам №1-9. НЕ подходит к №10, №11, №12

Голова Быка №1 | от 13000 ₽
https://mangal-craft.shop/tproduct/181653259882-podstavka-dlya-shampurov-golova-bika-1

Голова Быка №2 | от 13000 ₽
https://mangal-craft.shop/tproduct/447395034862-podstavka-dlya-shampurov-golova-bika-2

🌳 ШАШЛЫЧНЫЕ ДЕРЕВЬЯ — для духовки, тандыра, помпейской печи:
Характеристики: высота 28 см, длина шампуров 25 см, диаметр сковороды 24,5 см
Можно мыть в посудомойке.

№1 Одинарные шампуры | от 3700 ₽ | https://mangal-craft.shop/tproduct/146087506542-shashlichnoe-derevo-1
№2 Двойные шампуры | от 3800 ₽ | https://mangal-craft.shop/tproduct/979976780932-shashlichnoe-derevo-2
№3 Тройные шампуры | от 3900 ₽ | https://mangal-craft.shop/tproduct/898516090392-shashlichnoe-derevo-3
№4 Курник (для птицы) | от 3700 ₽ | https://mangal-craft.shop/tproduct/527507465212-shashlichnoe-derevo-4-kurnik
№5 Полный набор — ХИТ! | от 6800 ₽ | https://mangal-craft.shop/tproduct/963828086892-shashlichnoe-derevo-5

🔁 ВЕРТЕЛА:
Сборно-разборный (электрический + ручной) | от 53000 ₽
https://mangal-craft.shop/tproduct/726070706072-beptel-polnoctyu-sborno-razbornii

Для барана и поросёнка (ручной) | от 15000 ₽
https://mangal-craft.shop/tproduct/400910868972-vertel-dlya-zharki-barana-i-porosenka

FAQ:
- Нержавейка: AISI 304 (№12 — AISI 430)
- Посудомойка для шампуров: да, но для блеска лучше ручное мытьё
- Посудомойка для деревьев: да
- Ручка нагревается: у №1-9 и №12 — нет. У №10 и №11 — незначительно
- Для люля: лучший — №3, рекомендуй 21 мм
- Сроки отправки: до 5 дней, обычно 1–2 дня
- Маркетплейсы: нас там нет, только подделки
- Индивидуальный размер: возможно, звонить +7 (965) 014-19-28
- Морепродукты: да, подходят

ЛОГИКА ПОДБОРА:
- Люля/шашлык → №3 + 21 мм
- Овощи → №4 Компаньон
- Лаваш → №5
- Тандыр → №3 или №11
- Кафе → №10
- Длинные → №12 XXL
- Не могу выбрать → Комбо №6-9
- Подарок → Голова быка + набор №1-9, или Дерево №5
- Духовка → Шашлычное дерево
- Баран/поросёнок → Вертел

ДОСТАВКА:
- Только СДЭК, по РФ, мин. заказ 3000 ₽
- От 20000 ₽: международная доставка

ОГРАНИЧЕНИЯ:
1. НЕ запрашивай ФИО, телефон, адрес
2. НЕ считай доставку
3. НЕ оформляй заказы
4. Если дорого — объясни ценность, предложи более доступный вариант
5. Если не знаешь — направляй к @SVKolosov или +7 (965) 014-19-28
6. Всегда отправляй ссылку после рекомендации

ВАЖНО: Отвечай ТОЛЬКО на русском. Не используй Markdown (**, ##) — только текст и эмодзи."""

# ─── Промпт для группы ────────────────────────────────────────────────────────
GROUP_FILTER_PROMPT = """Ты модератор Telegram-группы магазина шампуров Mangal Craft.

Отвечай ТОЛЬКО словом YES или NO.

YES если сообщение содержит:
- Упоминание товаров: шампуры, мангал, люля, тандыр, барбекю, гриль, шашлык, вертел, набор, подставка
- Вопрос о товарах, заказе, доставке, ценах, характеристиках
- Просьбу о помощи с выбором

NO если:
- Только эмодзи (👍 🔥)
- Короткая реакция (ок, супер, класс)
- Явный офтоп
- Спам
- Сообщение от канала

Сомневаешься — YES.

Сообщение: """

# ─── История диалогов (Telegram) ──────────────────────────────────────────────
conversation_history: dict[int, list] = defaultdict(list)
MAX_HISTORY = 10

# ════════════════════════════════════════════════════════════════════════════
# ХРАНИЛИЩЕ ЭСКАЛАЦИЙ ВИДЖЕТА
# ════════════════════════════════════════════════════════════════════════════

class EscalationSession:
    """Активная эскалация: пользователь на сайте ждёт ответа оператора."""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.history: list[dict] = []          # полная история чата до эскалации
        self.operator_messages: list[dict] = [] # ответы оператора (для polling)
        self.created_at = time.time()
        self.last_activity = time.time()
        self.operator_notified = False

# session_id -> EscalationSession
active_escalations: dict[str, EscalationSession] = {}
# session_id -> список сообщений из виджета после эскалации (для истории)
escalation_pending_msgs: dict[str, list[str]] = defaultdict(list)

ESCALATION_TTL = 3600  # сессия живёт 1 час без активности

def cleanup_old_sessions():
    """Удаляем устаревшие эскалации."""
    now = time.time()
    to_delete = [
        sid for sid, s in active_escalations.items()
        if now - s.last_activity > ESCALATION_TTL
    ]
    for sid in to_delete:
        del active_escalations[sid]
        if sid in escalation_pending_msgs:
            del escalation_pending_msgs[sid]

WIDGET_ESCALATION_KEYWORDS = [
    "оператор", "человек", "менеджер", "живой", "реальный",
    "сотрудник", "специалист", "владимир", "сергей", "позови",
    "хочу поговорить", "соедини", "передай"
]

def is_escalation_request(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in WIDGET_ESCALATION_KEYWORDS)

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
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ОТПРАВКИ
# ════════════════════════════════════════════════════════════════════════════

async def safe_send(message: Message, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            reply_to_message_id=message.message_id
        )
        return
    except Exception as e1:
        logger.warning(f"⚠️ safe_send вариант 1 не сработал: {e1}")

    if message.message_thread_id:
        try:
            await bot.send_message(
                chat_id=message.chat.id,
                text=text,
                message_thread_id=message.message_thread_id
            )
            return
        except Exception as e2:
            logger.warning(f"⚠️ safe_send вариант 2 не сработал: {e2}")

    try:
        await bot.send_message(chat_id=message.chat.id, text=text)
    except Exception as e3:
        logger.error(f"❌ Не могу отправить сообщение: {e3}")


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
        return "⚠️ Небольшая задержка — попробуй ещё раз!"
    except Exception as e:
        logger.error(f"❌ Ошибка Claude API: {e}", exc_info=True)
        return "⚠️ Что-то пошло не так. Напиши @SVKolosov или позвони +7 (965) 014-19-28"


async def ask_claude_direct(messages: list) -> str:
    """Для виджета на сайте — без сохранения истории в памяти бота."""
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
                    "messages": messages,
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
    except Exception as e:
        logger.error(f"❌ Ошибка Claude API (widget): {e}")
        return "⚠️ Небольшая задержка — попробуйте ещё раз!"


async def should_reply_in_group(text: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": GROUP_FILTER_PROMPT + text}],
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"].strip().upper().startswith("YES")
    except Exception as e:
        logger.error(f"❌ Ошибка фильтра группы: {e}")
        return False


def clean_response(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'#{1,6}\s', '', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    return text.strip()


# ════════════════════════════════════════════════════════════════════════════
# УВЕДОМЛЕНИЕ ОПЕРАТОРА ОБ ЭСКАЛАЦИИ С САЙТА
# ════════════════════════════════════════════════════════════════════════════

async def notify_operator_escalation(session: EscalationSession, trigger_text: str) -> None:
    """Отправляет оператору уведомление с полной историей диалога."""
    if session.operator_notified:
        return
    session.operator_notified = True

    # Форматируем историю диалога
    history_lines = []
    for msg in session.history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            history_lines.append(f"👤 Клиент: {content}")
        elif role == "assistant":
            history_lines.append(f"🤖 Бот: {content}")

    history_text = "\n\n".join(history_lines) if history_lines else "(история пуста)"

    # Ограничиваем длину — Telegram лимит 4096 символов
    if len(history_text) > 2500:
        history_text = "...(сокращено)\n\n" + history_text[-2500:]

    text = (
        f"🚨 <b>Клиент просит живого оператора!</b>\n"
        f"🌐 Источник: виджет на сайте\n"
        f"🆔 Сессия: <code>{session.session_id[:8]}</code>\n\n"
        f"<b>История диалога:</b>\n"
        f"{'─' * 30}\n"
        f"{history_text}\n"
        f"{'─' * 30}\n\n"
        f"💬 <b>Триггер:</b> «{trigger_text}»\n\n"
        f"✏️ Чтобы ответить клиенту прямо в виджет:\n"
        f"<code>/reply {session.session_id[:8]} Ваш текст здесь</code>"
    )

    try:
        await bot.send_message(
            chat_id=OPERATOR_TELEGRAM_ID,
            text=text,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"✅ Оператор уведомлён об эскалации {session.session_id[:8]}")
    except Exception as e:
        logger.error(f"❌ Не могу уведомить оператора: {e}")


# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM HANDLERS
# ════════════════════════════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    logger.info(f"📩 /start от {user.full_name} (id={user.id})")
    conversation_history[user.id].clear()
    await safe_send(message,
        "🔥 Привет! Я консультант магазина Mangal Craft.\n\n"
        "Помогу выбрать шампуры, наборы и аксессуары для гриля 🍢\n\n"
        "Просто напиши что ищешь — например:\n"
        "  • шампуры для люля\n"
        "  • подарок для друга\n"
        "  • что лучше для тандыра\n\n"
        "Или напиши оператор — подключу живого специалиста."
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await safe_send(message,
        "ℹ️ Я помогу выбрать шампуры и аксессуары для гриля.\n\n"
        "Просто напиши что ищешь — отвечу как живой консультант!\n\n"
        "Для связи с оператором напиши: оператор"
    )


@dp.message(Command("reply"))
async def cmd_reply(message: Message) -> None:
    """
    Оператор отвечает клиенту виджета.
    Формат: /reply SESSION8 Текст ответа
    """
    if message.from_user.id != OPERATOR_TELEGRAM_ID:
        return  # только оператор

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await safe_send(message,
            "❌ Формат: /reply SESSION8 Текст ответа\n\n"
            "SESSION8 — первые 8 символов ID сессии из уведомления."
        )
        return

    session_prefix = parts[1].strip()
    reply_text = parts[2].strip()

    # Ищем сессию по префиксу
    matched = None
    for sid, session in active_escalations.items():
        if sid.startswith(session_prefix) or sid[:8] == session_prefix:
            matched = session
            break

    if not matched:
        await safe_send(message,
            f"❌ Сессия <code>{session_prefix}</code> не найдена или уже закрыта.\n"
            f"Активные сессии: {len(active_escalations)}"
        )
        return

    # Добавляем ответ оператора в очередь для polling
    matched.operator_messages.append({
        "role": "operator",
        "content": reply_text,
        "timestamp": time.time()
    })
    matched.last_activity = time.time()

    await safe_send(message, f"✅ Ответ отправлен клиенту!\n\n💬 «{reply_text}»")
    logger.info(f"✅ Оператор ответил в сессию {session_prefix}: «{reply_text}»")


@dp.message(Command("sessions"))
async def cmd_sessions(message: Message) -> None:
    """Показывает активные эскалации."""
    if message.from_user.id != OPERATOR_TELEGRAM_ID:
        return

    cleanup_old_sessions()

    if not active_escalations:
        await safe_send(message, "📭 Нет активных эскалаций с сайта.")
        return

    lines = [f"📋 <b>Активные сессии ({len(active_escalations)}):</b>\n"]
    for sid, s in active_escalations.items():
        age = int((time.time() - s.created_at) / 60)
        msgs_count = len(s.history)
        lines.append(
            f"• <code>{sid[:8]}</code> — {msgs_count} сообщ., {age} мин. назад\n"
            f"  /reply {sid[:8]} Ваш текст"
        )

    await safe_send(message, "\n".join(lines))


@dp.message(F.chat.type == ChatType.PRIVATE)
async def handle_private(message: Message) -> None:
    user = message.from_user
    text = message.text
    if not text:
        return
    text = text.strip()
    logger.info(f"📩 ЛИЧКА от {user.full_name} (id={user.id}): «{text}»")

    if any(kw in text.lower() for kw in ESCALATION_KEYWORDS):
        await escalate(message, reason="ключевое слово")
        return

    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    response = await ask_claude(user.id, text)
    await safe_send(message, clean_response(response))


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def handle_group(message: Message) -> None:
    text = message.text
    if not text:
        return
    text = text.strip()
    user = message.from_user

    if user and user.is_bot:
        return
    if message.sender_chat:
        logger.info(f"⏭️ Игнорирую сообщение от канала")
        return

    logger.info(f"📩 ГРУППА от {user.full_name if user else 'Unknown'}: «{text}»")

    if not await should_reply_in_group(text):
        logger.info(f"⏭️ Пропускаю: «{text}»")
        return

    logger.info(f"✅ Отвечаю в группе: «{text}»")

    if any(kw in text.lower() for kw in ESCALATION_KEYWORDS):
        await escalate(message, reason="ключевое слово в группе")
        return

    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    user_id = user.id if user else message.chat.id
    response = await ask_claude(user_id, text)
    await safe_send(message, clean_response(response))


# ════════════════════════════════════════════════════════════════════════════
# ЭСКАЛАЦИЯ (Telegram)
# ════════════════════════════════════════════════════════════════════════════

async def escalate(message: Message, reason: str = "") -> None:
    user = message.from_user
    await safe_send(message,
        "👨‍💼 Подключаю специалиста...\n\n"
        "Напиши напрямую: @SVKolosov (Сергей)\n"
        "Или позвони: +7 (965) 014-19-28 (Владимир) 😊\n\n"
        "💡 Мы делаем шампуры по индивидуальным размерам — уточни у Владимира!"
    )

    admin_handle = ADMIN_USERNAME.lstrip("@")
    admin_text = (
        f"🚨 <b>Запрос к оператору</b>\n\n"
        f"👤 {user.full_name if user else 'Неизвестный'}"
        + (f" (@{user.username})" if user and user.username else "")
        + f"\n🆔 <code>{user.id if user else '?'}</code>\n"
        f"💬 «{message.text}»\n"
        f"📌 Причина: {reason}"
    )
    try:
        await bot.send_message(chat_id=f"@{admin_handle}", text=admin_text)
    except Exception as e:
        logger.error(f"❌ Не могу уведомить @{admin_handle}: {e}")


# ════════════════════════════════════════════════════════════════════════════
# POLLING
# ════════════════════════════════════════════════════════════════════════════

async def start_polling_once() -> None:
    global _polling_started

    with _polling_lock:
        if _polling_started:
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
            allowed_updates=["message", "callback_query", "channel_post"],
            drop_pending_updates=True,
            handle_signals=False,
        )
    except asyncio.CancelledError:
        logger.info("⏹️ Polling остановлен")
    except Exception as e:
        logger.error(f"💥 Ошибка polling: {e}", exc_info=True)
    finally:
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mangal-craft.shop", "https://www.mangal-craft.shop"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok", "service": "Mangal Craft Bot"}


@app.get("/health")
@app.head("/health")
async def health():
    polling_alive = _polling_task is not None and not _polling_task.done()
    return {"status": "healthy", "polling": "running" if polling_alive else "stopped"}


@app.post("/widget-chat")
async def widget_chat(request: Request):
    """
    Основной endpoint виджета.
    Принимает: { messages, session_id }
    Возвращает: { reply, escalated, session_id }
    """
    try:
        cleanup_old_sessions()
        body = await request.json()
        messages = body.get("messages", [])
        session_id = body.get("session_id", str(uuid.uuid4()))

        if not messages:
            return JSONResponse({"reply": "Напишите ваш вопрос!", "escalated": False, "session_id": session_id})

        if len(messages) > 10:
            messages = messages[-10:]

        last_user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "")
                break

        # Проверяем — эскалация?
        if is_escalation_request(last_user_msg):
            # Создаём или обновляем сессию эскалации
            if session_id not in active_escalations:
                session = EscalationSession(session_id)
                active_escalations[session_id] = session
            else:
                session = active_escalations[session_id]

            session.history = messages.copy()
            session.last_activity = time.time()

            # Уведомляем оператора
            await notify_operator_escalation(session, last_user_msg)

            return JSONResponse({
                "reply": "👨‍💼 Подключаю живого специалиста!\n\nСейчас напишу Сергею — он ответит здесь в течение нескольких минут.\n\nЕсли срочно — звоните: +7 (965) 014-19-28 (Владимир) 🔥",
                "escalated": True,
                "session_id": session_id
            })

        # Если сессия уже в режиме эскалации — добавляем сообщение в очередь
        if session_id in active_escalations:
            session = active_escalations[session_id]
            session.history.append({"role": "user", "content": last_user_msg})
            session.last_activity = time.time()

            # Уведомляем оператора о новом сообщении
            try:
                await bot.send_message(
                    chat_id=OPERATOR_TELEGRAM_ID,
                    text=f"💬 <b>Новое сообщение от клиента</b>\n"
                         f"Сессия: <code>{session_id[:8]}</code>\n\n"
                         f"👤 «{last_user_msg}»\n\n"
                         f"<code>/reply {session_id[:8]} Ваш ответ</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

            return JSONResponse({
                "reply": "⏳ Специалист уже подключён — отвечу совсем скоро!",
                "escalated": True,
                "session_id": session_id
            })

        # Обычный режим — отвечает Claude
        reply = await ask_claude_direct(messages)
        reply = clean_response(reply)

        return JSONResponse({
            "reply": reply,
            "escalated": False,
            "session_id": session_id
        })

    except Exception as e:
        logger.error(f"❌ Ошибка widget-chat: {e}")
        return JSONResponse({"reply": "⚠️ Небольшая задержка — попробуйте ещё раз!", "escalated": False})


@app.get("/get-messages/{session_id}")
async def get_operator_messages(session_id: str):
    """
    Виджет polling — проверяет, есть ли новые ответы от оператора.
    Возвращает и очищает очередь сообщений.
    """
    if session_id not in active_escalations:
        return JSONResponse({"messages": [], "active": False})

    session = active_escalations[session_id]
    session.last_activity = time.time()

    # Забираем накопленные ответы оператора
    new_messages = session.operator_messages.copy()
    session.operator_messages.clear()

    return JSONResponse({
        "messages": new_messages,
        "active": True
    })


@app.post("/close-session/{session_id}")
async def close_session(session_id: str):
    """Виджет сообщает, что пользователь закрыл чат."""
    if session_id in active_escalations:
        del active_escalations[session_id]
        logger.info(f"🔒 Сессия {session_id[:8]} закрыта")
    return JSONResponse({"status": "closed"})


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
