"""Telegram панель управления Discord Self-Bot с красивым inline UI."""

import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config


def _is_owner(user_id: int) -> bool:
    """Проверка что команду отправил владелец."""
    return user_id == config.TELEGRAM_CHAT_ID


def _main_menu_kb(state) -> InlineKeyboardMarkup:
    """Главное меню с кнопками."""
    status_emoji = "🟢" if state.is_active else "🔴"
    voice_emoji = "🔊" if state.current_voice else "🔇"

    # Кнопка вкл/выкл зависит от текущего состояния
    if state.is_active:
        toggle_btn = InlineKeyboardButton(text="🔴 Выключить", callback_data="toggle_off")
    else:
        toggle_btn = InlineKeyboardButton(text="🟢 Включить", callback_data="toggle_on")

    keyboard = [
        [toggle_btn],
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="status"),
            InlineKeyboardButton(text="🔌 Выйти из войса", callback_data="disconnect_voice"),
        ],
        [
            InlineKeyboardButton(text="📝 Логи", callback_data="logs"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить меню", callback_data="refresh"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _settings_kb() -> InlineKeyboardMarkup:
    """Клавиатура настроек."""
    keyboard = [
        [InlineKeyboardButton(text="📝 AFK-сообщения", callback_data="settings_afk")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _back_kb() -> InlineKeyboardMarkup:
    """Кнопка назад."""
    keyboard = [
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _format_uptime(start_time: datetime) -> str:
    """Форматирование uptime."""
    delta = datetime.now() - start_time
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}ч {minutes}м {seconds}с"
    elif minutes > 0:
        return f"{minutes}м {seconds}с"
    return f"{seconds}с"


def _build_main_text(state) -> str:
    """Текст главного меню."""
    status = "🟢 Активен" if state.is_active else "🔴 Отключён"
    voice = f"🔊 `{state.current_voice}`" if state.current_voice else "🔇 Не подключён"
    uptime = _format_uptime(state.uptime_start) if state.uptime_start else "—"
    discord_user = f"`{state.discord_username}`" if state.discord_username else "⏳ Подключение..."

    return (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎮 *Discord Self\\-Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        f"👤 Аккаунт: {_escape_md(discord_user)}\n"
        f"📡 Статус: {_escape_md(status)}\n"
        f"🎙️ Войс: {_escape_md(voice)}\n"
        f"⏱️ Uptime: `{uptime}`\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Выбери действие:"
    )


def _escape_md(text: str) -> str:
    """Экранирование спецсимволов MarkdownV2 — пропускаем уже обёрнутое в backticks."""
    # Для простоты не экранируем — используем обычный Markdown
    return text


class TelegramPanel:
    """Telegram бот — панель управления."""

    def __init__(self, bot_state, discord_bot_ref):
        self.state = bot_state
        self.discord_bot = discord_bot_ref  # ссылка на Discord бот (для управления войсом)
        self.bot = Bot(
            token=config.TELEGRAM_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self.dp = Dispatcher()
        self._register_handlers()

    def _register_handlers(self):
        """Регистрация всех хендлеров."""

        @self.dp.message(Command("start"))
        async def cmd_start(message: Message):
            if not _is_owner(message.from_user.id):
                await message.answer("⛔ Доступ запрещён.")
                return
            await message.answer(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )

        @self.dp.message(Command("menu"))
        async def cmd_menu(message: Message):
            if not _is_owner(message.from_user.id):
                return
            await message.answer(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )

        # === Callback handlers ===

        @self.dp.callback_query(F.data == "toggle_on")
        async def cb_toggle_on(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return
            self.state.is_active = True
            self.state.add_log("Telegram", "Бот включён")
            await callback.answer("✅ Бот включён!")
            await callback.message.edit_text(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )

        @self.dp.callback_query(F.data == "toggle_off")
        async def cb_toggle_off(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return
            self.state.is_active = False
            self.state.add_log("Telegram", "Бот выключен")
            await callback.answer("🔴 Бот выключен! Отвечаю AFK-сообщениями.")
            await callback.message.edit_text(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )

        @self.dp.callback_query(F.data == "status")
        async def cb_status(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return

            status = "🟢 Активен" if self.state.is_active else "🔴 Отключён"
            voice = f"🔊 {self.state.current_voice}" if self.state.current_voice else "🔇 Не подключён"
            uptime = _format_uptime(self.state.uptime_start) if self.state.uptime_start else "—"
            discord_ok = "✅ Подключён" if self.state.discord_ready else "❌ Не подключён"
            total_cmds = len(self.state.logs)

            # Последние 3 команды
            recent = ""
            if self.state.logs:
                for log in self.state.logs[-3:]:
                    recent += f"\n  • `{log['user']}` → `{log['cmd']}` ({log['time']})"
            else:
                recent = "\n  Пока нет"

            text = (
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "📊 *Подробный статус*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "\n"
                f"📡 Режим: {status}\n"
                f"🌐 Discord: {discord_ok}\n"
                f"🎙️ Войс: {voice}\n"
                f"⏱️ Uptime: `{uptime}`\n"
                f"📊 Всего команд: `{total_cmds}`\n"
                f"\n🕐 *Последние команды:*{recent}"
            )

            await callback.message.edit_text(text, reply_markup=_back_kb())
            await callback.answer()

        @self.dp.callback_query(F.data == "disconnect_voice")
        async def cb_disconnect_voice(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return

            if self.discord_bot and self.discord_bot.voice_clients:
                await self.discord_bot.disconnect_voice()
                self.state.add_log("Telegram", "Вышел из войса")
                await callback.answer("🔌 Отключился от войса!")
            else:
                await callback.answer("🔇 Не подключён к войсу", show_alert=True)

            await callback.message.edit_text(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )

        @self.dp.callback_query(F.data == "logs")
        async def cb_logs(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return

            if not self.state.logs:
                text = (
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "📝 *Логи*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "\nПока ничего не произошло 🤷"
                )
            else:
                lines = []
                # Последние 10
                for log in self.state.logs[-10:]:
                    emoji = "🎮" if log["cmd"] in ("!call", "!dota") else "📩" if log["cmd"] == "!tg" else "⚙️"
                    lines.append(f"{emoji} `{log['time']}` — *{log['user']}* → `{log['cmd']}`")

                text = (
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "📝 *Последние события*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "\n" + "\n".join(lines)
                )

            await callback.message.edit_text(text, reply_markup=_back_kb())
            await callback.answer()

        @self.dp.callback_query(F.data == "settings")
        async def cb_settings(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return

            text = (
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚙️ *Настройки*\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            )
            await callback.message.edit_text(text, reply_markup=_settings_kb())
            await callback.answer()

        @self.dp.callback_query(F.data == "settings_afk")
        async def cb_settings_afk(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return

            afk_list = "\n".join(f"  {i+1}. {msg}" for i, msg in enumerate(config.AFK_MESSAGES))
            text = (
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "📝 *AFK-сообщения*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "\nТекущие сообщения:\n"
                f"{afk_list}\n"
                "\n_Чтобы изменить — отредактируй список_\n"
                "_AFK\\_MESSAGES в файле config.py_"
            )
            await callback.message.edit_text(text, reply_markup=_back_kb())
            await callback.answer()

        @self.dp.callback_query(F.data == "back_main")
        async def cb_back_main(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return
            await callback.message.edit_text(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )
            await callback.answer()

        @self.dp.callback_query(F.data == "refresh")
        async def cb_refresh(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return
            await callback.message.edit_text(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )
            await callback.answer("🔄 Обновлено!")

    async def send_notification(self, text: str):
        """Отправить уведомление владельцу."""
        try:
            await self.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=text,
            )
        except Exception as e:
            print(f"❌ Telegram notification error: {e}")

    async def start(self):
        """Запуск Telegram бота."""
        print("✅ Telegram: панель управления запущена")
        await self.dp.start_polling(self.bot)

    async def stop(self):
        """Остановка Telegram бота."""
        await self.bot.session.close()


def _build_main_text_simple(state) -> str:
    """Текст главного меню (обычный Markdown)."""
    status = "🟢 Активен" if state.is_active else "🔴 Отключён"
    voice = f"🔊 `{state.current_voice}`" if state.current_voice else "🔇 Не подключён"
    uptime = _format_uptime(state.uptime_start) if state.uptime_start else "—"
    discord_user = f"`{state.discord_username}`" if state.discord_username else "⏳ Подключение..."

    return (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎮 *Discord Self-Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        f"👤 Аккаунт: {discord_user}\n"
        f"📡 Статус: {status}\n"
        f"🎙️ Войс: {voice}\n"
        f"⏱️ Uptime: `{uptime}`\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Выбери действие 👇"
    )
