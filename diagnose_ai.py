# -*- coding: utf-8 -*-
"""
Диагностика подключения к Google Gemini (ИИ) — вставь в ячейку Colab и выполни.
Покажет, почему «Не удалось получить ответ от ИИ».
"""

import subprocess, sys, os
try:
    import openai
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openai"], check=False)
    import openai

# --- Вставь свой ключ Google AI Studio сюда (AIza...) --------------------
API_KEY = "ВПИШИ_КЛЮЧ_СЮДА"
# -------------------------------------------------------------------------
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

client = openai.OpenAI(api_key=API_KEY, base_url=BASE_URL)

print("=" * 50)
print("1) ПРОВЕРКА КЛЮЧА И СВЯЗИ С API")
print("=" * 50)
if not API_KEY or API_KEY.startswith("ВПИШИ"):
    print("❌ Ключ не вставлен! Впиши свой AIza... в переменную API_KEY выше.")
    sys.exit(1)

try:
    models = client.models.list()
    print("✅ API доступен, ключ рабочий.")
    print("   Ключ начинается с:", API_KEY[:6] + "...")
except Exception as e:
    print("❌ Не удалось подключиться к Gemini.")
    print("   Тип ошибки:", type(e).__name__)
    print("   Текст:", e)
    body = getattr(e, "body", None)
    if body:
        print("   Тело ответа от API:", body)
    sys.exit(1)

print()
print("=" * 50)
print("2) ДОСТУПНЫЕ МОДЕЛИ")
print("=" * 50)
try:
    ids = [m.id for m in models.data]
    print("   Доступно моделей:", len(ids))
    for mid in sorted(ids):
        if any(k in mid for k in ["gemini", "flash", "pro"]):
            print("   •", mid)
except Exception as e:
    print("   Не смог прочитать список моделей:", e)

print()
print("=" * 50)
print("3) ПРОБНЫЙ ЗАПРОС (текст)")
print("=" * 50)
MODEL_TEXT = "gemini-3.8-flash"
try:
    resp = client.chat.completions.create(
        model=MODEL_TEXT,
        messages=[{"role": "user", "content": "Ответь одним словом: работает?"}],
        temperature=0,
    )
    print("✅ Модель", MODEL_TEXT, "отвечает:", resp.choices[0].message.content.strip())
except Exception as e:
    print("❌ Модель", MODEL_TEXT, "не отвечает.")
    print("   Тип ошибки:", type(e).__name__)
    print("   Текст:", e)
    if "model_not_found" in str(e).lower() or "does not exist" in str(e).lower():
        print("   👉 ПРИЧИНА: такой модели нет. Возьми точное имя из списка выше,")
        print("   затем поменяй MODEL_TEXT / AI_MODEL в боте.")
    if "api key" in str(e).lower() or "invalid" in str(e).lower():
        print("   👉 ПРИЧИНА: неверный ключ. Скопируй заново с ai studio.")
    if "rate" in str(e).lower() or "limit" in str(e).lower() or "quota" in str(e).lower():
        print("   👉 ПРИЧИНА: исчерпан лимит бесплатной квоты.")
        print("   Подожди минуту (у Flash квота щедрая) или смени ключ.")