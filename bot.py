"""
bot.py
------
Главный модуль Telegram-бота «EcoVoice Bot».

Возможности:
    /start   — приветствие текстом + голосовым сообщением;
    текст    — ИИ-анализ вопроса, ответ текстом + голосовым сообщением;
    фото     — скачивание во temp/, ИИ-оценка экологичности, вердикт +
               голосовое сообщение; временные файлы затем удаляются.

Библиотека: aiogram 3 (async). Запуск:  python bot.py
Перед запуском заполните .env (BOT_TOKEN, AI_API_KEY).
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv

import ai_service
import voice_service

# --- Настройка логирования: всё пишем в консоль, без обрыва при сбоях ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("EcoVoiceBot")

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Папка для временных файлов фото (создаётся при первом использовании).
PHOTO_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "temp"
)

os.makedirs(PHOTO_DIR, exist_ok=True)

# Инициализация объекта бота и диспетчера.
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- Вспомогательные функции -------------------------------------------------

async def _send_text_and_voice(message: Message, text: str) -> None:
    """
    Отправляет пользователю ответ текстом, а затем голосовым сообщением.

    Автоматически удаляет созданный голосовой файл после отправки.

    :param message: исходное сообщение (для ответа)
    :param text: текст ответа (заодно отправляется и озвученный)
    """
    # Сначала текстовый ответ.
    await message.answer(text)

    voice_path: str | None = None
    try:
        # Синтез голоса (OPUS -> отображается как голосовое сообщение).
        voice_path = await voice_service.text_to_voice(
            text, output_format="opus"
        )
        # FSInputFile передаёт файл по абсолютному пути.
        await message.answer_voice(FSInputFile(voice_path))
    except Exception:  # noqa: BLE001 — голос не критичен для пользователя
        logger.exception("Не удалось отправить голосовое сообщение")
        await message.answer("⚠️ Не смог озвучить ответ, но он есть выше.")
    finally:
        # Обязательно удаляем временный аудиофайл.
        voice_service.cleanup_voice(voice_path)


# --- Обработчики сообщений ---------------------------------------------------

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Приветствие, описание возможностей, голосовое сообщение."""
    text = (
        "👋 Привет! Я EcoVoice Bot — помогаю снижать личный "
        "углеродный след.\n\n"
        "Что я умею:\n"
        "🌍 Отвечать на вопросы об экологии и климате;\n"
        "📸 Сканировать фото товаров или чеков и оценивать "
        "их экологичность;\n"
        "🎙️ Отвечать текстом и голосовым сообщением.\n\n"
        "Задай вопрос или пришли фото покупки!"
    )
    await _send_text_and_voice(message, text)


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    """
    Обработчик фото: скачивание во temp/, ИИ-оценка экологичности,
    вердикт текстом и голосом, затем удаление временных файлов.
    """
    # Статус "записывает голосовое сообщение", пока идёт обработка.
    await bot.send_chat_action(message.chat.id, "record_voice")

    # Самое большое доступное разрешение (последний элемент списка).
    photo = message.photo[-1]
    photo_path: str | None = None

    try:
        # Скачиваем фото во временную папку с уникальным именем.
        file = await bot.get_file(photo.file_id)
        photo_path = os.path.join(PHOTO_DIR, f"{photo.file_id}.jpg")
        await bot.download_file(file.file_path, destination=photo_path)
        logger.info("Фото сохранено: %s", photo_path)

        # Статус "печатает" — анализ изображения идёт.
        await bot.send_chat_action(message.chat.id, "typing")

        # Мультимодальный анализ экологичности фото.
        verdict = await ai_service.analyze_image(photo_path)

        # Отправляем итог текстом и голосом.
        await _send_text_and_voice(message, verdict)

    except Exception:  # noqa: BLE001
        logger.exception("Ошибка при обработке фото:")
        await message.answer(
            "😔 Не удалось проанализировать фото. Попробуй ещё раз позже."
        )
    finally:
        # Убираем временный файл фото — он больше не нужен.
        if photo_path:
            try:
                os.remove(photo_path)
                logger.info("Временный файл фото удалён: %s", photo_path)
            except OSError:
                logger.exception("Не удалось удалить файл фото")


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    """Анализ вопроса через ИИ, ответ текстом + голосовым сообщением."""
    # Статус: готовим голосовой ответ.
    await bot.send_chat_action(message.chat.id, "record_voice")

    try:
        # Анализируем текст вопроса через ИИ.
        answer = await ai_service.analyze_text(message.text)

        await bot.send_chat_action(message.chat.id, "typing")
        # Отправляем ответ (текст + голос), удаляя звук после отправки.
        await _send_text_and_voice(message, answer)

    except Exception:  # noqa: BLE001
        logger.exception("Ошибка при обработке текста:")
        await message.answer(
            "😔 Не удалось получить ответ от ИИ. "
            "Проверь API-ключ или попробуй позже."
        )


# --- Точка входа -------------------------------------------------------------

async def main() -> None:
    """Запускает long-polling — постоянный опрос обновлений от Telegram."""
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN не задан! Создай файл .env и укажи "
            "BOT_TOKEN=... и AI_API_KEY=..."
        )
    logger.info("EcoVoice Bot запущен. Нажмите Ctrl+C для остановки.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
