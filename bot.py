"""Точка входа — запуск Discord Self-Bot и Telegram панели параллельно."""

import asyncio
import signal
from datetime import datetime

import config
from discord_bot import DiscordSelfBot
from telegram_panel import TelegramPanel


class BotState:
    """Общее состояние между Discord и Telegram ботами."""

    def __init__(self):
        self.is_active: bool = True
        self.current_voice: str | None = None
        self.discord_username: str | None = None
        self.discord_ready: bool = False
        self.uptime_start: datetime = datetime.now()
        self.logs: list[dict] = []

    def add_log(self, user: str, cmd: str):
        """Добавить запись в лог."""
        self.logs.append({
            "user": user,
            "cmd": cmd,
            "time": datetime.now().strftime("%H:%M:%S"),
        })
        # Храним последние 50 записей
        if len(self.logs) > 50:
            self.logs = self.logs[-50:]


async def main():
    """Главная функция — запуск обоих ботов."""
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🎮 Discord Self-Bot + Telegram Panel")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()

    # Общее состояние
    state = BotState()

    # Создаём Telegram панель (нужна для отправки уведомлений)
    # Discord бот будет передан позже
    tg_panel = TelegramPanel(bot_state=state, discord_bot_ref=None)

    # Создаём Discord бот с функцией отправки уведомлений
    discord_bot = DiscordSelfBot(
        bot_state=state,
        telegram_notify_func=tg_panel.send_notification,
    )

    # Передаём ссылку на Discord бот в Telegram панель
    tg_panel.discord_bot = discord_bot

    # Запускаем оба бота параллельно
    print("🚀 Запускаю ботов...")
    print()

    async def run_discord():
        try:
            await discord_bot.start(config.DISCORD_TOKEN)
        except Exception as e:
            print(f"❌ Discord ошибка: {e}")
            await tg_panel.send_notification(f"❌ *Discord ошибка:*\n`{e}`")

    async def run_telegram():
        try:
            await tg_panel.start()
        except Exception as e:
            print(f"❌ Telegram ошибка: {e}")

    # Запускаем параллельно
    try:
        await asyncio.gather(
            run_discord(),
            run_telegram(),
        )
    except KeyboardInterrupt:
        print("\n⏹️ Останавливаю ботов...")
    finally:
        # Cleanup
        if discord_bot.voice_clients:
            await discord_bot.disconnect_voice()
        if not discord_bot.is_closed():
            await discord_bot.close()
        await tg_panel.stop()
        print("👋 Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Выход.")
