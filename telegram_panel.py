"""Telegram панель управления Discord Self-Bot с красивым inline UI."""

import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.markdown import html_decoration as hd
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

import config


class TTSStates(StatesGroup):
    waiting_for_tts_text = State()


def _is_owner(user_id: int) -> bool:
    """Проверка что команду отправил владелец."""
    return user_id == config.TELEGRAM_CHAT_ID


def _main_menu_kb(state) -> InlineKeyboardMarkup:
    """Главное меню с кнопками."""
    # Кнопка вкл/выкл зависит от текущего состояния
    if state.is_active:
        toggle_btn = InlineKeyboardButton(text="💤 Выключить бота", callback_data="toggle_off")
    else:
        toggle_btn = InlineKeyboardButton(text="⚡ Включить бота", callback_data="toggle_on")

    ai_status = "🟢 Вкл" if state.is_ai_active else "🔴 Выкл"
    ai_btn = InlineKeyboardButton(text=f"🤖 Автоответчик ИИ: {ai_status}", callback_data="toggle_ai")

    keyboard = [
        [toggle_btn],
        [ai_btn],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="status"),
            InlineKeyboardButton(text="🔇 Покинуть войс", callback_data="disconnect_voice"),
        ],
        [
            InlineKeyboardButton(text="📜 Журнал логов", callback_data="logs"),
            InlineKeyboardButton(text="⚙️ Настройки AFK", callback_data="settings"),
        ],
        [
            InlineKeyboardButton(text="🗣 Озвучить текст", callback_data="tts_prompt"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _settings_kb() -> InlineKeyboardMarkup:
    """Клавиатура настроек."""
    keyboard = [
        [InlineKeyboardButton(text="📝 Список AFK-ответов", callback_data="settings_afk")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _back_kb() -> InlineKeyboardMarkup:
    """Кнопка назад."""
    keyboard = [
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_main")],
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
    return _build_main_text_simple(state)


def _esc(text: str) -> str:
    """Экранирование HTML-спецсимволов для Telegram HTML parse mode."""
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TelegramPanel:
    """Telegram бот — панель управления."""

    def __init__(self, bot_state, discord_bot_ref):
        self.state = bot_state
        self.discord_bot = discord_bot_ref  # ссылка на Discord бот (для управления войсом)
        self.bot = Bot(
            token=config.TELEGRAM_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
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
            if self.discord_bot:
                await self.discord_bot.set_active(True)
            else:
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
            if self.discord_bot:
                await self.discord_bot.set_active(False)
            else:
                self.state.is_active = False
            self.state.add_log("Telegram", "Бот выключен")
            await callback.answer("🔴 Бот выключен!")
            await callback.message.edit_text(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )

        @self.dp.callback_query(F.data == "status")
        async def cb_status(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return

            status = "🟢 <b>Активен</b>" if self.state.is_active else "💤 <b>Выключен</b>"
            voice = f"🔊 <code>{_esc(self.state.current_voice)}</code>" if self.state.current_voice else "🔇 <i>Не подключён</i>"
            uptime = _format_uptime(self.state.uptime_start) if self.state.uptime_start else "—"
            discord_ok = "🟢 <b>В сети</b>" if self.state.discord_ready else "🔴 <b>Оффлайн</b>"
            total_cmds = len(self.state.logs)

            # Последние 3 команды
            recent = ""
            if self.state.logs:
                for log in self.state.logs[-3:]:
                    emoji = "🎮" if log["cmd"] in ("!call", "!dota") else "📩" if log["cmd"] == "!tg" else "⚙️"
                    recent += f"\n  {emoji} <code>{_esc(log['time'])}</code> | <b>{_esc(log['user'])}</b> → <code>{_esc(log['cmd'])}</code>"
            else:
                recent = "\n  <i>Событий пока нет</i>"

            text = (
                "╔══════════════════════╗\n"
                "📊 <b>ПОДРОБНЫЙ МОНИТОРИНГ</b>\n"
                "╚══════════════════════╝\n\n"
                f"📡 <b>Режим работы:</b> {status}\n"
                f"🌐 <b>Discord клиент:</b> {discord_ok}\n"
                f"🎙️ <b>Канал голосовой:</b> {voice}\n"
                f"⏱️ <b>Время работы (Uptime):</b> <code>{uptime}</code>\n"
                f"📊 <b>Всего событий в логе:</b> <code>{total_cmds}</code>\n\n"
                f"🕐 <b>Последние действия:</b>{recent}"
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
                    "╔══════════════════════╗\n"
                    "📜 <b>ЖУРНАЛ СОБЫТИЙ</b>\n"
                    "╚══════════════════════╝\n\n"
                    "<i>Журнал пуст. Жду активности в Discord... 💤</i>"
                )
            else:
                lines = []
                # Последние 10
                for log in self.state.logs[-10:]:
                    emoji = "🎮" if log["cmd"] in ("!call", "!dota") else "📩" if log["cmd"] == "!tg" else "⚙️"
                    lines.append(f"{emoji} <code>{_esc(log['time'])}</code> | <b>{_esc(log['user'])}</b> → <code>{_esc(log['cmd'])}</code>")

                text = (
                    "╔══════════════════════╗\n"
                    "📜 <b>ЖУРНАЛ СОБЫТИЙ (ЛОГИ)</b>\n"
                    "╚══════════════════════╝\n\n"
                    "" + "\n".join(lines)
                )

            await callback.message.edit_text(text, reply_markup=_back_kb())
            await callback.answer()

        @self.dp.callback_query(F.data == "settings")
        async def cb_settings(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return

            text = (
                "╔══════════════════════╗\n"
                "⚙️ <b>КОНФИГУРАЦИЯ БОТА</b>\n"
                "╚══════════════════════╝"
            )
            await callback.message.edit_text(text, reply_markup=_settings_kb())
            await callback.answer()

        @self.dp.callback_query(F.data == "settings_afk")
        async def cb_settings_afk(callback: CallbackQuery):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return

            afk_list = "\n".join(f"  🔹 {i+1}. <i>{_esc(msg)}</i>" for i, msg in enumerate(config.AFK_MESSAGES))
            text = (
                "╔══════════════════════╗\n"
                "📝 <b>СПИСОК AFK-ОТВЕТОВ</b>\n"
                "╚══════════════════════╝\n\n"
                "<b>Текущие шаблоны ответов:</b>\n"
                f"{afk_list}\n\n"
                "ℹ️ <i>Для изменения отредактируйте переменную AFK_MESSAGES в конфигурационном файле config.py</i>"
            )
            await callback.message.edit_text(text, reply_markup=_back_kb())
            await callback.answer()

        @self.dp.callback_query(F.data == "back_main")
        async def cb_back_main(callback: CallbackQuery, state: FSMContext):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return
            await state.clear()
            await callback.message.edit_text(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )
            await callback.answer()

        @self.dp.callback_query(F.data == "refresh")
        async def cb_refresh(callback: CallbackQuery, state: FSMContext):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return
            await state.clear()
            await callback.message.edit_text(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )
            await callback.answer("🔄 Обновлено!")

        @self.dp.callback_query(F.data == "toggle_ai")
        async def cb_toggle_ai(callback: CallbackQuery, state: FSMContext):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return
            await state.clear()
            self.state.is_ai_active = not self.state.is_ai_active
            status_str = "включён" if self.state.is_ai_active else "выключен"
            self.state.add_log("Telegram", f"ИИ автоответчик {status_str}")
            await callback.answer(f"🤖 Режим ИИ: {'🟢 Включен' if self.state.is_ai_active else '🔴 Выключен'}")
            await callback.message.edit_text(
                _build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )

        @self.dp.callback_query(F.data == "tts_prompt")
        async def cb_tts_prompt(callback: CallbackQuery, state: FSMContext):
            if not _is_owner(callback.from_user.id):
                await callback.answer("⛔ Нет доступа", show_alert=True)
                return

            if not self.state.current_voice:
                await callback.answer("❌ Бот не подключен к голосовому каналу!", show_alert=True)
                return

            await state.set_state(TTSStates.waiting_for_tts_text)

            keyboard = [[InlineKeyboardButton(text="◀️ Отмена", callback_data="back_main")]]
            await callback.message.edit_text(
                "🗣 <b>Озвучка текста в голосовой канал Discord</b>\n\n"
                "Введите текст, который вы хотите произнести в войсе:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            await callback.answer()

        @self.dp.message(Command("say"))
        async def cmd_say(message: Message, state: FSMContext):
            if not _is_owner(message.from_user.id):
                return
            await state.clear()

            args = message.text.split(maxsplit=1)
            if len(args) < 2 or not args[1].strip():
                await message.answer("⚠️ Использование: <code>/say привет всем</code>")
                return

            text_to_say = args[1].strip()

            if not self.state.current_voice:
                await message.answer("❌ Бот не в войсе! Зайдите сначала через Discord или командами <code>!call</code> / <code>!dota</code>.")
                return

            if self.discord_bot:
                success = await self.discord_bot.play_tts(text_to_say)
                if success:
                    self.state.add_log("Telegram", f"/say: {text_to_say[:20]}")
                    await message.answer(f"🗣 Озвучиваю в войсе: <i>{_esc(text_to_say)}</i>")
                else:
                    await message.answer("❌ Не удалось воспроизвести озвучку.")
            else:
                await message.answer("❌ Ошибка связи с Discord-клиентом.")

        @self.dp.message(TTSStates.waiting_for_tts_text, F.text)
        async def handle_tts_text(message: Message, state: FSMContext):
            if not _is_owner(message.from_user.id):
                return

            if not message.text:
                await message.answer("⚠️ Пожалуйста, отправьте текстовое сообщение.")
                return

            text_to_say = message.text.strip()
            await state.clear()

            if not text_to_say:
                await message.answer("⚠️ Текст не может быть пустым.")
                await message.answer(
                    _build_main_text_simple(self.state),
                    reply_markup=_main_menu_kb(self.state),
                )
                return

            if not self.state.current_voice:
                await message.answer("❌ Бот не подключен к голосовому каналу!")
                await message.answer(
                    _build_main_text_simple(self.state),
                    reply_markup=_main_menu_kb(self.state),
                )
                return

            if self.discord_bot:
                success = await self.discord_bot.play_tts(text_to_say)
                if success:
                    self.state.add_log("Telegram", f"TTS: {text_to_say[:20]}")
                    await message.answer(
                        f"🗣 Озвучиваю в войсе: <i>{_esc(text_to_say)}</i>\n\n" + _build_main_text_simple(self.state),
                        reply_markup=_main_menu_kb(self.state),
                    )
                else:
                    await message.answer(
                        "❌ Не удалось воспроизвести озвучку.\n\n" + _build_main_text_simple(self.state),
                        reply_markup=_main_menu_kb(self.state),
                    )
            else:
                await message.answer(
                    "❌ Ошибка связи с Discord-клиентом.\n\n" + _build_main_text_simple(self.state),
                    reply_markup=_main_menu_kb(self.state),
                )

        from aiogram.filters import StateFilter
        @self.dp.message(F.voice, StateFilter("*"))
        async def handle_telegram_voice(message: Message, state: FSMContext):
            if not _is_owner(message.from_user.id):
                return
            await state.clear()

            if not self.state.current_voice:
                await message.answer("❌ Бот не подключен к голосовому каналу! Зайдите сначала в войс через Discord (или используйте команды <code>!call</code> / <code>!dota</code>).")
                return

            status_msg = await message.answer("📥 Загружаю голосовое сообщение...")

            import uuid
            import os
            temp_filename = f"/tmp/tg_voice_{uuid.uuid4().hex}.ogg"

            try:
                # Получаем и скачиваем файл
                file_id = message.voice.file_id
                file = await self.bot.get_file(file_id)
                await self.bot.download_file(file.file_path, temp_filename)

                await status_msg.edit_text("🔊 Воспроизвожу ваше голосовое сообщение в Discord...")

                if self.discord_bot:
                    success = await self.discord_bot.play_audio_file(temp_filename, delete_after=True)
                    if success:
                        self.state.add_log("Telegram", "Голосовое из TG")
                        await status_msg.edit_text("✅ Голосовое сообщение воспроизведено в войсе!")
                    else:
                        await status_msg.edit_text("❌ Не удалось воспроизвести голосовое сообщение.")
                else:
                    await status_msg.edit_text("❌ Ошибка связи с Discord-клиентом.")

            except Exception as e:
                print(f"❌ Ошибка при загрузке/проигрывании голосового из TG: {e}")
                await status_msg.edit_text(f"❌ Произошла ошибка при обработке голосового: {e}")
                if os.path.exists(temp_filename):
                    try:
                        os.remove(temp_filename)
                    except:
                        pass

    async def send_main_menu(self):
        """Отправить главное меню (панель управления) в Telegram."""
        try:
            await self.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=_build_main_text_simple(self.state),
                reply_markup=_main_menu_kb(self.state),
            )
        except Exception as e:
            print(f"❌ Ошибка отправки главного меню в Telegram: {e}")

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
    """Текст главного меню (HTML)."""
    status = "🟢 <b>АКТИВЕН</b>" if state.is_active else "💤 <b>ВЫКЛЮЧЕН</b> (режим ожидания)"
    voice = f"🔊 <code>{_esc(state.current_voice)}</code>" if state.current_voice else "🔇 <i>Не в войсе</i>"
    uptime = _format_uptime(state.uptime_start) if state.uptime_start else "—"
    discord_user = f"👤 <code>{_esc(state.discord_username)}</code>" if state.discord_username else "⏳ <i>Авторизация...</i>"

    return (
        "╔══════════════════════╗\n"
        "🎮 <b>DISCORD SELF-BOT PANEL</b>\n"
        "╚══════════════════════╝\n\n"
        f"<b>👤 Аккаунт:</b> {discord_user}\n"
        f"<b>⚡ Режим:</b> {status}\n"
        f"<b>🎙️ Войс:</b> {voice}\n"
        f"<b>⏱️ Uptime:</b> <code>{uptime}</code>\n\n"
        "📊 <i>Выберите действие на панели управления ниже:</i>"
    )
