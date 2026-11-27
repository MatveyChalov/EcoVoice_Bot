"""
ai_service.py
-------------
Сервис ИИ (OpenAI-совместимый API chat/completions):
анализ текста и изображений для экобота.

Благодаря OpenAI-совместимости модуль работает и с OpenAI (gpt-4o),
и с другими провайдерами (Google Gemini через endpoint /v1beta/openai/,
GigaChat, YandexGPT, DeepSeek и т.п.) — достаточно поменять значения
в .env: AI_BASE_URL, AI_MODEL.

Модуль не зависит от Telegram и может тестироваться отдельно.
"""

from __future__ import annotations

import base64
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- Конфигурация ИИ из переменных окружения ---
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "gemini-3.8-flash")

# Модель для анализа изображений. Может отличаться от текстовой (например,
# у Groq), поэтому выносим её в отдельную переменную.
# По умолчанию используем ту же модель, что и для текста.
AI_VISION_MODEL = os.getenv("AI_VISION_MODEL", AI_MODEL)

# Системная инструкция: задаёт роли "эколог-помощник" и формат ответов.
# Важно: просим модель дописывать в конец краткую карточку, чтобы голосовой
# ответ не был слишком длинным — TTS быстро читает длинный текст утомительно.
SYSTEM_PROMPT = (
    "Ты — EcoVoice Bot, дружелюбный ИИ-помощник по экологии и снижению "
    "углеродного следа. На русском языке отвечай на вопросы об экологии, "
    "давай конкретные советы по сокращению личного углеродного следа. "
    "Отвечай сжато (до 600–800 знаков), в конце добавь блок КАРТОЧКА: "
    "с тезисами на 1–3 строки."
)

# Инициализируем клиент OpenAI. Если ключ не задан — поднимется исключение
# при первом вызове, а бот перехватит его и вежливо сообщит пользователю.
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Ленивое создание клиента ИИ (один на всё время работы процесса)."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    return _client


def _file_to_base64_data_url(path: str) -> str:
    """Кодирует файл изображения в data URL (base64) для передачи в модель."""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    # Угадываем MIME-тип по расширению (достаточно для jpg/png/webp).
    ext = os.path.splitext(path)[1].lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")

    return f"data:{mime};base64,{data}"


def analyze_text(user_text: str) -> str:
    """
    Анализирует текстовое сообщение пользователя и возвращает ответ модели.

    :param user_text: вопрос или сообщение пользователя
    :return: строковый ответ ИИ на русском языке
    :raises RuntimeError: если API недоступно или вернуло пустой ответ
    """
    response = _get_client().chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0.5,
    )

    # Извлекаем текст первого выбранного варианта ответа.
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Модель вернула пустой ответ.")
    return content.strip()


def analyze_image(image_path: str) -> str:
    """
    Оценивает экологичность товара/покупки/чека по фотографии.

    :param image_path: путь к временному файлу изображения
    :return: строковый вердикт (эковердикт) на русском языке
    :raises RuntimeError: если API недоступно или вернуло пустой ответ
    """
    image_url = _file_to_base64_data_url(image_path)

    response = _get_client().chat.completions.create(
        model=AI_VISION_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Проанализируй изображение: товар, упаковка "
                            "или чек. Оцени экологичность: материал, "
                            "перерабатываемость, наличие пластика, упаковка, "
                            "альтернативы. Вердикт: от 0 до 10 (где 10 — "
                            "очень экологично) и 2–3 конкретных совета. "
                            "В конце добавь блок КАРТОЧКА: с тезисами "
                            "на 1–3 строки."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                ],
            },
        ],
        temperature=0.5,
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Модель вернула пустой ответ по изображению.")
    return content.strip()
