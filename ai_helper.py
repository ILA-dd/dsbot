"""Хелпер для интеграции ИИ (OpenRouter & Gemini) в автоответчик."""

import aiohttp
import config

async def _call_openrouter(model: str, messages: list[dict]) -> str | None:
    """Внутренний хелпер для выполнения запроса к OpenRouter."""
    if not config.OPENROUTER_API_KEY:
        return None
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ila/dsbot",
        "X-Title": "Discord Self Bot"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 250
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if 'choices' in data and len(data['choices']) > 0:
                        content = data['choices'][0]['message']['content']
                        if content:
                            return content.strip()
                else:
                    err_text = await resp.text()
                    print(f"❌ OpenRouter API ({model}) response error ({resp.status}): {err_text}")
    except Exception as e:
        print(f"❌ OpenRouter API ({model}) request failed: {e}")
    return None

async def _call_gemini(model: str, payload: dict) -> str | None:
    """Внутренний хелпер для выполнения запроса к Gemini API."""
    if not config.GEMINI_API_KEY:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={config.GEMINI_API_KEY}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if 'candidates' in data and len(data['candidates']) > 0:
                        candidate = data['candidates'][0]
                        if candidate.get('finishReason') == 'SAFETY':
                            print(f"⚠️ Gemini ({model}) заблокировал ответ по фильтрам безопасности!")
                            return "SAFETY_BLOCKED"
                        part = candidate['content']['parts'][0]
                        if 'text' in part:
                            return part['text'].strip()
                else:
                    err_text = await resp.text()
                    print(f"❌ Gemini API ({model}) response error ({resp.status}): {err_text}")
    except Exception as e:
        print(f"❌ Gemini API ({model}) request failed: {e}")
    return None

import re

def clean_response(text: str) -> str:
    """Очищает сгенерированный ответ ИИ от случайных префиксов времени в квадратных скобках."""
    if not text:
        return text
    # Удаляем точные префиксы относительного времени в квадратных скобках в начале сообщения,
    # например [только что], [5 мин. назад], [2 ч. назад], [1 дн. назад]
    cleaned = re.sub(r'^\[(?:только что|\d+\s*(?:мин\.|ч\.|дн\.)\s*назад)\]\s*', '', text)
    return cleaned.strip()

async def generate_response(system_instruction: str, history_messages: list[dict]) -> str:
    """Генерация ответа через OpenRouter с фолбэком на Gemini."""
    # 1. Сначала пробуем OpenRouter, если есть API-ключ
    if config.OPENROUTER_API_KEY:
        # Форматируем историю для OpenRouter (OpenAI-совместимый формат)
        messages = [{"role": "system", "content": system_instruction}]
        for msg in history_messages:
            role = "assistant" if msg["is_self"] else "user"
            content = msg["text"]
            if "time_ago" in msg:
                content = f"[{msg['time_ago']}] {content}"
            messages.append({"role": role, "content": content})

        openrouter_models = [
            "meta-llama/llama-3-8b-instruct:free",
            "google/gemma-2-9b-it:free",
            "openrouter/auto"
        ]
        for model in openrouter_models:
            print(f"🤖 Пробую сгенерировать ответ через OpenRouter ({model})...")
            res = await _call_openrouter(model, messages)
            if res:
                return clean_response(res)

    # 2. Если OpenRouter не настроен или дал ошибку — пробуем Gemini
    if config.GEMINI_API_KEY:
        # Форматируем историю для Gemini
        contents = []
        for msg in history_messages:
            role = "model" if msg["is_self"] else "user"
            content = msg["text"]
            if "time_ago" in msg:
                content = f"[{msg['time_ago']}] {content}"
            contents.append({
                "role": role,
                "parts": [{"text": content}]
            })
        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 250},
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]
        }
        gemini_models = [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-flash-latest"
        ]
        for model in gemini_models:
            print(f"🤖 Пробую сгенерировать ответ через Gemini ({model})...")
            res = await _call_gemini(model, payload)
            if res == "SAFETY_BLOCKED":
                return "а че"
            if res:
                return clean_response(res)

    return ""

async def analyze_style(chat_history: list[dict], self_username: str) -> str:
    """Анализирует стиль общения через OpenRouter с фолбэком на Gemini."""
    # Форматируем диалог для анализа
    dialog_text = ""
    for msg in chat_history:
        sender = "Я" if msg["is_self"] else "Собеседник"
        dialog_text += f"{sender}: {msg['text']}\n"
        
    prompt = (
        f"Проанализируй диалог ниже. Мои сообщения помечены как 'Я', сообщения собеседника — 'Собеседник'.\n"
        f"Твоя задача — детально изучить и кратко описать стиль общения 'Я' с этим конкретным собеседником.\n"
        f"Обрати внимание на следующие особенности:\n"
        f"1. Регистр букв: пишу ли я только строчными буквами или использую заглавные? Пишу ли я имена собственные с большой буквы?\n"
        f"2. Пунктуация: ставлю ли я точки в конце предложений? Использую ли запятые, восклицательные и вопросительные знаки?\n"
        f"3. Манера общения и тон: дружелюбный, саркастичный, сухой, эмоциональный, расслабленный?\n"
        f"4. Сленг и сокращения: какие сокращения (типа 'ща', 'че', 'пж') или сленговые слова я употребляю?\n"
        f"5. Длина и структура сообщений: отвечаю ли короткими фразами, разбиваю ли одну мысль на несколько сообщений, или пишу длинными абзацами?\n"
        f"6. Смайлики и эмодзи: использую ли классические эмодзи, или ставлю закрывающие/открывающие скобки (например, ')', '((', ')))'), или вообще не использую смайлики?\n\n"
        f"Напиши краткое и точное описание стиля общения 'Я' (на русском языке, 1-2 абзаца). Это описание будет использовано в качестве инструкции для ИИ, который будет отвечать вместо меня.\n\n"
        f"Диалог для анализа:\n{dialog_text}"
    )

    # 1. Пробуем OpenRouter
    if config.OPENROUTER_API_KEY:
        messages = [{"role": "user", "content": prompt}]
        openrouter_models = [
            "meta-llama/llama-3-8b-instruct:free",
            "google/gemma-2-9b-it:free",
            "openrouter/auto"
        ]
        for model in openrouter_models:
            print(f"⚙️ Пробую анализировать стиль через OpenRouter ({model})...")
            res = await _call_openrouter(model, messages)
            if res:
                return res

    # 2. Пробуем Gemini
    if config.GEMINI_API_KEY:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]
        }
        gemini_models = [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-flash-latest"
        ]
        for model in gemini_models:
            print(f"⚙️ Пробую анализировать стиль через Gemini ({model})...")
            res = await _call_gemini(model, payload)
            if res == "SAFETY_BLOCKED":
                return "Отвечай коротко и просто."
            if res:
                return res

    return "Отвечай коротко и просто."


import base64

async def transcribe_audio(filepath: str) -> str | None:
    """Распознает речь из аудиофайла с помощью Gemini API."""
    if not config.GEMINI_API_KEY:
        print("❌ Gemini API Key is missing for transcription.")
        return None

    try:
        # Читаем файл и кодируем в base64
        with open(filepath, "rb") as f:
            audio_bytes = f.read()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        mime_type = "audio/ogg"
        if filepath.endswith(".mp3"):
            mime_type = "audio/mp3"
        elif filepath.endswith(".wav"):
            mime_type = "audio/wav"

        # Формируем payload для Gemini API
        payload = {
            "contents": [{
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": audio_b64
                        }
                    },
                    {
                        "text": "Распознай русскую речь из этого аудиофайла и напиши только текст сообщения, без лишних комментариев и форматирования."
                    }
                ]
            }],
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]
        }

        # Используем те же модели, что и для генерации текста
        gemini_models = [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
            "gemini-flash-latest"
        ]

        for model in gemini_models:
            print(f"🤖 Пробую распознать аудио через Gemini ({model})...")
            res = await _call_gemini(model, payload)
            if res:
                return res

    except Exception as e:
        print(f"❌ Ошибка при распознавании аудиофайла через Gemini: {e}")
    
    return None

