# -*- coding: utf-8 -*-
"""
EcoVoice Bot — полностью автономный скрипт для Google Colab.
Один кусок кода: установка зависимостей, ИИ, голос, и запуск бота.
Вставь этот код в одну ячейку Colab (или сохрани как .py и запусти).
"""

# ====================================================================
# 1. УСТАНОВКА ЗАВИСИМОСТЕЙ (выполняется при первом запуске)
# ====================================================================
import subprocess
import sys

# Пробуем импортировать aiogram; если его нет — ставим зависимости.
try:
    import aiogram  # noqa: F401
    print("Зависимости уже установлены — пропускаем установку.")
except ImportError:
    # В Colab: ставим ffmpeg + libopus (для голосовых) и Python-пакеты.
    # Вывод установки подавляем — слишком длинный.
    subprocess.run(
        "apt-get update -qq && apt-get install -y -qq ffmpeg libopus0",
        shell=True, check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "aiogram", "python-dotenv", "openai", "edge-tts"],
        check=False,
    )
    print("Зависимости установлены.")

import asyncio
import logging
import os
import base64
import shutil

# ====================================================================
# 2. НАСТРОЙКИ (вставь свои данные)
# ====================================================================
BOT_TOKEN = ""      # от @BotFather в Telegram
AI_API_KEY = ""     # ключ Google AI Studio (aistudio.google.com -> Get API key)

# Конфигурация ИИ (Google Gemini, OpenAI-совместимый API)
AI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
AI_MODEL = "gemini-3.8-flash"                  # текстовая модель
AI_VISION_MODEL = "gemini-3.8-flash"           # та же модель умеет видеть фото

assert BOT_TOKEN and AI_API_KEY, "Впиши BOT_TOKEN и AI_API_KEY в раздел НАСТРОЙКИ!"

TEMP = "temp"
os.makedirs(TEMP, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("EcoVoiceBot")

# ====================================================================
# 3. ИИ-СЕРВИС (анализ текста и изображений через Gemini)
# ====================================================================
import time
from openai import OpenAI

SYSTEM_PROMPT = (
    "Ты — EcoVoice Bot, дружелюбный ИИ-помощник по экологии и снижению "
    "углеродного следа. На русском языке отвечай на вопросы об экологии, "
    "давай конкретные советы по сокращению личного углеродного следа. "
    "Отвечай сжато (до 600-800 знаков), в конце добавь блок КАРТОЧКА: "
    "с тезисами на 1-3 строки."
)

# Список моделей, пробуемых по очереди на случай перегрузки (503/429).
# Gemini на бесплатном тарифе часто отдаёт "high demand" — падаем с первой
# модели на следующую, а не тревожим пользователя ошибкой.
MODELS_CANDIDATES = [
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

# Сколько раз пробуем очередную модель (с паузой, чтобы пережить пик).
RETRIES_PER_MODEL = 3
RETRY_DELAY_SEC = 5


def _chat_completion_with_retry(client, model, messages):
    """
    Делает запрос к модели, перебирая запасные модели и повторяя попытки.

    :return: текст ответа
    :raises RuntimeError: если все модели исчерпаны или ошибка не про 503/429
    """
    # Пробуем все модели по очереди.
    for model_name in MODELS_CANDIDATES:
        for attempt in range(RETRIES_PER_MODEL):
            try:
                resp = client.chat.completions.create(
                    model=model_name, messages=messages, temperature=0.5,
                )
                content = resp.choices[0].message.content
                if content:
                    return content.strip()
            except Exception as e:  # noqa: BLE001
                reason = str(e)
                # Только перегрузка/лимит — пробуем снова или другую модель.
                if ("503" in reason or "429" in reason
                        or "high demand" in reason or "UNAVAILABLE" in reason
                        or "quota" in reason.lower()):
                    logger.warning(
                        "Модель %s временно недоступна (%s). Попытка %s",
                        model_name, type(e).__name__, attempt + 1,
                    )
                    # Последняя попытка этой модели — короткая пауза перед
                    # переходом на следующую, чтобы пережить пик нагрузки.
                    if attempt + 1 < RETRIES_PER_MODEL:
                        time.sleep(RETRY_DELAY_SEC)
                    continue
                # Одна и та же модель — всё равно не повторим, выходим сразу.
                raise
    raise RuntimeError(
        "Все ИИ-модели временно недоступны (перегрузка/лимит). Попробуй позже."
    )


def analyze_text(user_text: str) -> str:
    """Анализ текстового вопроса через ИИ (с автоповтором и запасными)."""
    client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    return _chat_completion_with_retry(
        client, AI_MODEL,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    )


def analyze_image(image_path: str) -> str:
    """Оценка экологичности по фото (товар/чек/упаковка)."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64}"
    client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    return _chat_completion_with_retry(
        client, AI_VISION_MODEL,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Проанализируй изображение: товар, упаковка или "
                            "чек. Оцени экологичность: материал, "
                            "перерабатываемость, наличие пластика, упаковка, "
                            "альтернативы. Вердикт: от 0 до 10 (где 10 — очень "
                            "экологично) и 2-3 конкретных совета. В конце "
                            "добавь блок КАРТОЧКА: с тезисами на 1-3 строки."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    )

# ====================================================================
# 4. ГОЛОСОВОЙ СЕРВИС (edge-tts + ffmpeg -> OGG/Opus)
# ====================================================================
import edge_tts


async def _generate_opus(text: str, out_path: str) -> str:
    """Синтез речи и конвертация в OGG/Opus (формат голосового)."""
    mp3 = out_path + ".mp3"
    async with edge_tts.Communicate(text, "ru-RU-SvetlanaNeural", rate="-10%") as tts:
        await tts.save(mp3)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3,
         "-c:a", "libopus", "-b:a", "48k", out_path],
        capture_output=True,
    )
    if os.path.exists(mp3):
        os.remove(mp3)
    return out_path


def cleanup(*paths):
    """Безопасное удаление временных файлов."""
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

# ====================================================================
# 5. ЛОГИКА БОТА (aiogram 3)
# ====================================================================
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


async def _send_text_and_voice(message: Message, text: str) -> None:
    """Отправляет ответ текстом, затем голосовым сообщением."""
    await message.answer(text)
    voice_path = None
    try:
        voice_path = await _generate_opus(text, os.path.join(TEMP, "voice.ogg"))
        await message.answer_voice(FSInputFile(voice_path))
    except Exception:
        logger.exception("Не удалось отправить голосовое сообщение")
        await message.answer("Не смог озвучить, но текст есть выше.")
    finally:
        cleanup(voice_path, os.path.join(TEMP, "voice.ogg"))


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Приветствие + голосовое сообщение."""
    await bot.send_chat_action(message.chat.id, "record_voice")
    text = (
        "Привет! Я EcoVoice Bot — помогаю снижать личный углеродный след. "
        "Могу отвечать на вопросы об экологии и сканировать фото товаров "
        "или чеков, оценивая их экологичность. Пришли вопрос или фото!"
    )
    await _send_text_and_voice(message, text)


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Обработка фото: скачивание, ИИ-вердикт, голос, очистка."""
    await bot.send_chat_action(message.chat.id, "record_voice")
    photo = message.photo[-1]
    photo_path = None
    try:
        await bot.send_chat_action(message.chat.id, "typing")
        file = await bot.get_file(photo.file_id)
        photo_path = os.path.join(TEMP, f"{photo.file_id}.jpg")
        await bot.download_file(file.file_path, destination=photo_path)
        logger.info("Фото сохранено: %s", photo_path)
        verdict = analyze_image(photo_path)
        await _send_text_and_voice(message, verdict)
    except Exception:
        logger.exception("Ошибка при обработке фото:")
        await message.answer("Не удалось проанализировать фото. Попробуй ещё раз.")
    finally:
        cleanup(photo_path)


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    """Обработка текста: ИИ-ответ + голос."""
    await bot.send_chat_action(message.chat.id, "record_voice")
    try:
        await bot.send_chat_action(message.chat.id, "typing")
        answer = analyze_text(message.text)
        await _send_text_and_voice(message, answer)
    except Exception as e:
        logger.exception("Ошибка при обработке текста:")
        # Показываем пользователю причину — так проще отладить.
        reason = str(e)
        if "model_not_found" in reason or "does not exist" in reason:
            await message.answer(
                "Не удалось получить ответ: такой ИИ-модели нет в аккаунте. "
                "Поменяй AI_MODEL (см. aistudio.google.com)."
            )
        elif "401" in reason or "Invalid API key" in reason:
            await message.answer(
                "Не удалось получить ответ: неверный API-ключ. "
                "Проверь AI_API_KEY в настройках бота."
            )
        elif "rate" in reason.lower() or "quota" in reason.lower() or "429" in reason:
            await message.answer(
                "Не удалось получить ответ: закончился лимит запросов. "
                "Подожди минуту или смени ключ."
            )
        else:
            await message.answer(
                f"Не удалось получить ответ от ИИ. Причина: {reason[:200]}"
            )

# ====================================================================
# 6. ЗАПУСК (блокирующий await — ячейка живёт, пока жив бот)
# ====================================================================
print("Бот запускается... Нажми /start в Telegram.")
logger.info("EcoVoice Bot запущен")
await bot.delete_webhook(drop_pending_updates=True)
await dp.start_polling(bot)
