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
import random

SLANG_FALLBACKS = [
    "че", "а че", "да ладно", "ясно", "пофиг", "бля", "че за бред", "да не", "ппц", "мда", "хз", "лан", "пон"
]

def get_slang_fallback() -> str:
    return random.choice(SLANG_FALLBACKS)

def is_refusal(text: str) -> bool:
    """Проверяет, является ли ответ стандартным отказом ИИ по безопасности/этике."""
    if not text:
        return False
    lower_text = text.lower()
    refusal_patterns = [
        "i am sorry",
        "i'm sorry",
        "i cannot",
        "i am not able",
        "i'm not able",
        "i'm not going to continue",
        "i am not going to continue",
        "cannot continue this conversation",
        "as an ai",
        "as a large language model",
        "my safety guidelines",
        "ethical guidelines",
        "я не могу",
        "я не буду",
        "не могу ответить",
        "извините, но я",
        "не могу продолжать",
        "прости, но я"
    ]
    for pattern in refusal_patterns:
        if pattern in lower_text:
            return True
    return False

def merge_consecutive_messages(history_messages: list[dict]) -> list[dict]:
    """
    Объединяет подряд идущие сообщения от одного и того же отправителя в одно.
    Каждое новое сообщение внутри блока начинается с новой строки с его таймстампом.
    Картинки сохраняются в списке `images` соответствующего блока.
    """
    merged = []
    for msg in history_messages:
        role_is_self = msg["is_self"]
        text = msg["text"]
        time_ago = msg.get("time_ago")
        image = msg.get("image")
        
        # Форматируем текст с таймстампом, если он есть
        formatted_text = text
        if time_ago:
            formatted_text = f"[{time_ago}] {text}"
            
        if merged and merged[-1]["is_self"] == role_is_self:
            merged[-1]["text"] += f"\n{formatted_text}"
            if image:
                if "images" not in merged[-1]:
                    merged[-1]["images"] = []
                merged[-1]["images"].append(image)
        else:
            merged.append({
                "is_self": role_is_self,
                "text": formatted_text,
                "images": [image] if image else []
            })
    return merged

async def _call_groq(model: str, messages: list[dict]) -> str | None:
    """Внутренний хелпер для выполнения запроса к Groq API."""
    if not config.GROQ_API_KEY:
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json"
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
                    print(f"❌ Groq API ({model}) response error ({resp.status}): {err_text}")
    except Exception as e:
        print(f"❌ Groq API ({model}) request failed: {e}")
    return None

async def do_call_provider(provider: str, system_instruction: str, merged_history: list[dict]) -> str | None:
    """Выполняет вызов конкретного API-провайдера с его моделями и настройками."""
    provider = provider.strip().lower()
    has_images = any(len(msg.get("images", [])) > 0 for msg in merged_history)
    
    if provider == "groq":
        if not config.GROQ_API_KEY:
            return None
            
        messages = [{"role": "system", "content": system_instruction}]
        for msg in merged_history:
            role = "assistant" if msg["is_self"] else "user"
            if msg.get("images"):
                content_list = [{"type": "text", "text": msg["text"]}]
                for img in msg["images"]:
                    content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img['mime_type']};base64,{img['data']}"
                        }
                    })
                messages.append({"role": role, "content": content_list})
            else:
                messages.append({"role": role, "content": msg["text"]})
            
        groq_models = []
        if has_images:
            groq_models.extend([
                "llama-3.2-11b-vision-preview",
                "llama-3.2-90b-vision-preview"
            ])
        else:
            if config.GROQ_MODEL:
                groq_models.append(config.GROQ_MODEL)
            groq_models.extend([
                "llama-3.3-70b-specdec",
                "llama-3.1-70b-versatile",
                "llama3-70b-8192",
                "gemma2-9b-it"
            ])
            
        # Убираем дубликаты
        seen = set()
        groq_models = [m for m in groq_models if m and not (m in seen or seen.add(m))]
        
        for model in groq_models:
            print(f"🤖 Пробую сгенерировать ответ через Groq ({model})...")
            res = await _call_groq(model, messages)
            if res and not is_refusal(res):
                return clean_response(res)
                
    elif provider == "openrouter":
        if not config.OPENROUTER_API_KEY:
            return None
            
        messages = [{"role": "system", "content": system_instruction}]
        for msg in merged_history:
            role = "assistant" if msg["is_self"] else "user"
            if msg.get("images"):
                content_list = [{"type": "text", "text": msg["text"]}]
                for img in msg["images"]:
                    content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img['mime_type']};base64,{img['data']}"
                        }
                    })
                messages.append({"role": role, "content": content_list})
            else:
                messages.append({"role": role, "content": msg["text"]})
            
        openrouter_models = []
        if config.OPENROUTER_MODEL:
            openrouter_models.append(config.OPENROUTER_MODEL)
            
        openrouter_models.append("qwen/qwen3.6-27b")
        openrouter_models.append("qwen/qwen-2.5-vl-72b")
        
        if has_images:
            openrouter_models.extend([
                "google/gemini-2.5-flash",
                "meta-llama/llama-3.2-11b-vision-instruct:free",
                "qwen/qwen-2.5-vl-72b"
            ])
        else:
            openrouter_models.extend([
                "meta-llama/llama-3-8b-instruct:free",
                "google/gemma-2-9b-it:free",
                "openrouter/auto"
            ])
            
        # Убираем дубликаты
        seen = set()
        openrouter_models = [m for m in openrouter_models if m and not (m in seen or seen.add(m))]
        
        for model in openrouter_models:
            print(f"🤖 Пробую сгенерировать ответ через OpenRouter ({model})...")
            res = await _call_openrouter(model, messages)
            if res and not is_refusal(res):
                return clean_response(res)
                
    elif provider == "gemini":
        if not config.GEMINI_API_KEY:
            return None
        contents = []
        for msg in merged_history:
            role = "model" if msg["is_self"] else "user"
            parts = [{"text": msg["text"]}]
            if msg.get("images"):
                for img in msg["images"]:
                    parts.append({
                        "inlineData": {
                            "mimeType": img["mime_type"],
                            "data": img["data"]
                        }
                    })
            contents.append({
                "role": role,
                "parts": parts
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
                continue
            if res and not is_refusal(res):
                return clean_response(res)
                
    return None

def clean_response(text: str) -> str:
    """Очищает сгенерированный ответ ИИ от случайных префиксов времени в квадратных скобках."""
    if not text:
        return text
    # Удаляем точные префиксы относительного времени в квадратных скобках в начале сообщения,
    # например [только что], [5 мин. назад], [2 ч. назад], [1 дн. назад]
    cleaned = re.sub(r'^\[(?:только что|\d+\s*(?:мин\.|ч\.|дн\.)\s*назад)\]\s*', '', text)
    return cleaned.strip()

async def generate_response(system_instruction: str, history_messages: list[dict]) -> str:
    """Генерация ответа через Groq, OpenRouter или Gemini с поддержкой fallback-очереди."""
    merged_history = merge_consecutive_messages(history_messages)
    if not merged_history:
        return get_slang_fallback()

    # Очередь провайдеров для попыток
    providers_to_try = []
    preferred = config.AI_PROVIDER.strip().lower() if config.AI_PROVIDER else "fallback"
    
    # Парсим настройки fallback
    fallback_order = []
    if config.AI_FALLBACK_ORDER:
        fallback_order = [p.strip().lower() for p in config.AI_FALLBACK_ORDER.split(",") if p.strip()]
    if not fallback_order:
        fallback_order = ["groq", "openrouter", "gemini"]
        
    if preferred in ["groq", "openrouter", "gemini"]:
        providers_to_try.append(preferred)
        for p in fallback_order:
            if p not in providers_to_try:
                providers_to_try.append(p)
    else:
        providers_to_try = fallback_order

    # Пробуем по очереди
    for provider in providers_to_try:
        try:
            res = await do_call_provider(provider, system_instruction, merged_history)
            if res:
                return res
        except Exception as e:
            print(f"❌ Ошибка при вызове провайдера {provider}: {e}")

    # Если все провайдеры дали сбой или отказались отвечать, возвращаем сленговый фолбэк
    return get_slang_fallback()

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

