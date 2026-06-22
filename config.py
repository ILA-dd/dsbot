"""Загрузка конфигурации из .env файла."""

import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require(var_name: str) -> str:
    """Получить обязательную переменную окружения или завершить программу."""
    value = os.getenv(var_name)
    if not value or value.startswith("твой") or value.startswith("токен"):
        print(f"❌ Переменная {var_name} не задана в .env файле!")
        sys.exit(1)
    return value


# === Токены ===
DISCORD_TOKEN: str = _require("DISCORD_TOKEN")
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: int = int(_require("TELEGRAM_CHAT_ID"))

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
