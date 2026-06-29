"""Загрузка конфигурации из .env файла."""

import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require(var_name: str) -> str:
    """Получить обязательную переменную окружения или завершить программу."""
    value = os.getenv(var_name)
    if not value or value.startswith(("твой", "токен", "your_")) or value.endswith("_here"):
        print(f"❌ Переменная {var_name} не задана в .env файле!")
        sys.exit(1)
    return value


# === Токены ===
DISCORD_TOKEN: str = _require("DISCORD_TOKEN")
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: int = int(_require("TELEGRAM_CHAT_ID"))

# === Дополнительно (ИИ-автоответчик) ===
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY: str | None = os.getenv("OPENROUTER_API_KEY")

# === AFK-сообщения ===
AFK_MESSAGES: list[str] = [
    "Сейчас отошёл, скоро буду 🕐",
    "Не у компа, позже зайду 💤",
    "Отошёл по делам ✌️",
    "Сейчас не могу, напишу когда вернусь 📵",
    "Отошёл ненадолго, скоро буду!",
    "Занят, но скоро вернусь 🔜",
    "Отлучился, позже отвечу ✍️",
]
