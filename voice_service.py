"""
voice_service.py
----------------
Сервис синтеза речи (TTS): превращает текст в голосовое сообщение
в формате OGG/OPUS, который Telegram корректно отображает как "voice message".

Пайплайн:
    1. edge-tts генерирует MP3 из текста (высокое качество русского голоса).
    2. ffmpeg конвертирует MP3 -> OGG (кодек Opus). Именно этот формат
       Telegram распознаёт и проигрывает как голосовое, а не аудио.
    3. При вызове cleanup_voice() временные файлы удаляются.

Если ffmpeg не установлен в системе — бот отправит голосовое одним файлом
MP3, но Telegram в этом случае отобразит его как аудиозапись (audio).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile

import edge_tts

# Голос edge-tts: максимально естественный русский женский голос.
TTS_VOICE = "ru-RU-SvetlanaNeural"

# Скорость чтения (чуть медленнее обычного — приятнее на слух).
TTS_RATE = "-10%"

# Папка для временных файлов звука (создаётся при необходимости).
VOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")


def _ensure_voice_dir() -> None:
    """Гарантирует существование папки для временных аудиофайлов."""
    os.makedirs(VOICE_DIR, exist_ok=True)


async def _generate_mp3(text: str, mp3_path: str) -> None:
    """Генерирует MP3-файл речи из текста через edge-tts."""
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE, rate=TTS_RATE)
    await communicate.save(mp3_path)


def _convert_to_opus(mp3_path: str, ogg_path: str) -> bool:
    """
    Конвертирует MP3 в OGG/Opus через ffmpeg.

    :return: True, если преобразование удалось; False, если ffmpeg недоступен.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # Запасные пути для Windows (winget поставляет ffmpeg через WinGet, но
        # обновлённый PATH виден только в новых сессиях терминала).
        fallback = (
            r"C:\Users\User\AppData\Local\Microsoft\WinGet\Packages"
            r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
            r"\ffmpeg-9.1-full_build\bin\ffmpeg.exe"
        )
        if os.path.exists(fallback):
            ffmpeg = fallback
    if not ffmpeg:
        return False

    cmd = [
        ffmpeg,
        "-y",
        "-loglevel", "error",
        "-i", mp3_path,
        "-c:a", "libopus",
        "-b:a", "48k",
        ogg_path,
    ]
    result = __import__("subprocess").run(cmd, capture_output=True)
    return os.path.exists(ogg_path) and result.returncode == 0


async def text_to_voice(
    text: str,
    output_path: str | None = None,
    output_format: str = "opus",
) -> str:
    """
    Синтезирует речь из текста и сохраняет в аудиофайл.

    :param text: текст для озвучивания
    :param output_path: путь к итоговому файлу; по умолчанию создаётся в temp/
    :param output_format: "opus" (OGG — голосовое сообщение) или "mp3"
    :return: абсолютный путь к созданному аудиофайлу
    :raises RuntimeError: если синтез речи не удался
    """
    _ensure_voice_dir()

    # Если путь не задан — генерируем уникальное имя во временной папке.
    if output_path is None:
        suffix = ".ogg" if output_format == "opus" else ".mp3"
        tmp_file = tempfile.NamedTemporaryFile(
            dir=VOICE_DIR, suffix=suffix, delete=False
        )
        output_path = tmp_file.name
        tmp_file.close()

    # Путь к промежуточному MP3 (если нужна конвертация в opus).
    intermediate_mp3 = None

    try:
        if output_format == "opus":
            # Сначала MP3, затем сконвертируем в OGG/Opus.
            intermediate_mp3 = output_path.rsplit(".", 1)[0] + "_raw.mp3"
            await _generate_mp3(text, intermediate_mp3)
            if not _convert_to_opus(intermediate_mp3, output_path):
                # ffmpeg недоступен — возвращаем MP3 как есть (без голосового).
                shutil.copy2(intermediate_mp3, output_path)
            return output_path

        # Просто MP3 без конвертации.
        await _generate_mp3(text, output_path)
        return output_path

    finally:
        # Подчищаем промежуточный MP3, чтобы не копить мусор.
        if intermediate_mp3 and os.path.exists(intermediate_mp3):
            os.remove(intermediate_mp3)


def cleanup_voice(*paths: str | None) -> None:
    """
    Безопасно удаляет временные аудиофайлы после отправки.

    :param paths: пути к файлам, которые нужно удалить
    """
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                # Если файл занят — просто пропускаем, не роняя бота.
                pass


# Небольшой самопроверочный запуск:  python voice_service.py  "Привет, мир!"
if __name__ == "__main__":
    demo = asyncio.run(
        text_to_voice("Привет! Я помогу снизить углеродный след.")
    )
    print("Создан demo-файл:", demo)
    cleanup_voice(demo)
