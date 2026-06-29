"""Discord Self-Bot — обработка команд !call, !dota, !tg в личных сообщениях."""

import random
import asyncio
from datetime import datetime, timedelta, timezone

import discord

import config
import ai_helper


class DiscordSelfBot(discord.Client):
    """Self-bot клиент Discord с обработкой DM-команд."""

    def __init__(self, bot_state, tg_panel):
        # Минимальные интенты — нужны guilds, voice_states, dm_messages
        super().__init__()
        self.state = bot_state
        self.tg_panel = tg_panel
        self.tg_notify = tg_panel.send_notification
        self.tg_timestamps = {}  # user_id: list of datetime
        self.last_greeting_time = {}  # user_id: datetime
        self.voice_timestamps = {}  # user_id: datetime
        self.user_styles = {}  # user_id: style_description (кэш стилей общения)
        self.ai_tasks = {}  # user_id: active asyncio Task for AI response (debounce)
        self.voice_transcripts = {}  # msg_id: transcribed_text (кэш для голосовых сообщений)

    def _should_send_greeting(self, user_id: int) -> bool:
        """
        Проверяет, прошло ли 2 минуты с момента последней отправки приветствия/AFK-сообщения
        этому пользователю. Предотвращает спам.
        """
        now = datetime.now()
        last_time = self.last_greeting_time.get(user_id)
        if last_time and now - last_time < timedelta(minutes=2):
            return False
        self.last_greeting_time[user_id] = now
        return True

    def _is_auto_reply(self, content: str) -> bool:
        """
        Проверяет, является ли сообщение автоматическим ответом бота или командой.
        """
        if not content:
            return False
        content_lower = content.lower()
        
        # Игнорируем команды пользователя (начинаются на !)
        if content.strip().startswith("!"):
            return True

        # Проверяем все AFK-сообщения из конфигурации
        for afk_m in config.AFK_MESSAGES:
            if afk_m.lower() in content_lower:
                return True
        
        # Проверяем другие известные паттерны автоответов
        auto_patterns = [
            "🤖 **я сейчас не у компьютера",
            "👋 привет! я сейчас на связи",
            "⚠️ команды !call",
            "иду в доту! зашёл",
            "отправил уведомление в telegram",
            "не в голосовом канале",
            "я уже с тобой в канале"
        ]
        for pattern in auto_patterns:
            if pattern in content_lower:
                return True
                
        # Проверяем паттерн "зашёл в ... (микрофон выкл 🔇)"
        if "зашёл в" in content_lower and "микрофон выкл" in content_lower:
            return True
            
        return False

    def _get_time_ago_str(self, created_at, now_utc) -> str:
        """
        Возвращает текстовое представление относительного времени (например, "5 мин. назад").
        """
        diff = now_utc - created_at
        seconds = int(diff.total_seconds())
        if seconds < 0:
            seconds = 0
        if seconds < 60:
            return "только что"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} мин. назад"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} ч. назад"
        days = hours // 24
        return f"{days} дн. назад"

    def _check_tg_cooldown(self, user_id: int) -> tuple[bool, int]:
        """
        Проверяет лимит команды !tg: максимум 3 раза за 5 минут.
        Возвращает (is_allowed, seconds_left).
        """
        now = datetime.now()
        if user_id not in self.tg_timestamps:
            self.tg_timestamps[user_id] = []
            
        # Удаляем таймстампы старше 5 минут
        self.tg_timestamps[user_id] = [t for t in self.tg_timestamps[user_id] if now - t < timedelta(minutes=5)]
        
        if len(self.tg_timestamps[user_id]) >= 3:
            oldest = self.tg_timestamps[user_id][0]
            seconds_left = int((oldest + timedelta(minutes=5) - now).total_seconds())
            return False, max(seconds_left, 1)
            
        return True, 0

    async def on_ready(self):
        print(f"✅ Discord: залогинен как {self.user} (ID: {self.user.id})")
        self.state.discord_username = str(self.user)
        self.state.discord_ready = True

        # Устанавливаем статус «Не беспокоить»
        try:
            await self.change_presence(status=discord.Status.dnd)
        except Exception as e:
            print(f"❌ Ошибка установки статуса при запуске: {e}")

        # Уведомляем в Telegram о запуске отправкой главного меню
        await self.tg_panel.send_main_menu()

    async def on_message(self, message: discord.Message):
        # Игнорируем свои сообщения
        if message.author.id == self.user.id:
            return

        # Обрабатываем только DM
        if not isinstance(message.channel, discord.DMChannel):
            return

        content = message.content.strip().lower()
        username = str(message.author)
        user_id = message.author.id

        # Отменяем ожидающий автоответ, если пришло любое новое сообщение от этого пользователя
        if user_id in self.ai_tasks:
            self.ai_tasks[user_id].cancel()

        # Проверяем команды в первую очередь (работают даже если бот выключен/AFK, отправляя автоответы)
        if content == "!call":
            await self._handle_call(message, username, user_id, "call")
        elif content == "!dota":
            await self._handle_call(message, username, user_id, "dota")
        elif content == "!tg":
            await self._handle_tg(message, username)
        elif content == "!help":
            await self._handle_help(message, username)
        else:
            # Любое другое сообщение — показываем список команд или отвечаем через ИИ
            if not self.state.is_active:
                if self.state.is_ai_active and (config.GEMINI_API_KEY or config.OPENROUTER_API_KEY or config.GROQ_API_KEY):
                    self.ai_tasks[user_id] = asyncio.create_task(self._respond_with_ai(message))
                else:
                    # Бот выключен и ИИ-автоответчик выключен — ничего не пишем
                    pass
            else:
                await self._handle_unknown(message, username)

    async def on_voice_state_update(self, member, before, after):
        """Отслеживание изменений голосовых каналов для обновления статуса в TG-панели."""
        if member.id == self.user.id:
            # Проверяем, подключен ли бот к голосовым каналам в текущей сессии
            connected_channels = [vc.channel for vc in self.voice_clients if vc.is_connected()]
            if connected_channels:
                vc_channel = connected_channels[0]
                self.state.current_voice = f"{vc_channel.guild.name} / #{vc_channel.name}"
            else:
                self.state.current_voice = None

    async def _handle_call(self, message: discord.Message, username: str, user_id: int, cmd_type: str):
        """Обработка !call и !dota — заход в войс к отправителю."""
        # Логируем
        self.state.add_log(username, f"!{cmd_type}")

        # Если бот выключен — AFK ответ
        if not self.state.is_active:
            if self._should_send_greeting(user_id):
                afk_msg = random.choice(config.AFK_MESSAGES)
                await message.channel.send(afk_msg)
                await self.tg_notify(
                    f"📩 <b>Команда в AFK-режиме</b>\n"
                    f"👤 От: <code>{username}</code>\n"
                    f"💬 Команда: <code>!{cmd_type}</code>\n"
                    f"🔴 Ответил AFK-сообщением"
                )
            return

        # Ищем пользователя в голосовых каналах
        voice_channel = self._find_user_voice_channel(user_id)

        if not voice_channel:
            await message.channel.send("❌ Ты не в голосовом канале! Зайди в войс и попробуй снова.")
            await self.tg_notify(
                f"📩 <b>Новая команда</b>\n"
                f"👤 От: <code>{username}</code>\n"
                f"💬 Команда: <code>!{cmd_type}</code>\n"
                f"⚠️ Пользователь не в голосовом канале"
            )
            return

        # Проверяем, подключены ли мы уже к этому каналу
        for vc in self.voice_clients:
            if vc.channel.id == voice_channel.id:
                if cmd_type == "dota":
                    await message.channel.send(f"🎮 Я уже с тобой в канале **{voice_channel.name}**! Иду в доту! 🔇")
                else:
                    await message.channel.send(f"👋 Я уже с тобой в канале **{voice_channel.name}**! (микрофон выкл 🔇)")
                await self.tg_notify(
                    f"📩 <b>Команда в войсе</b>\n"
                    f"👤 От: <code>{username}</code>\n"
                    f"💬 Команда: <code>!{cmd_type}</code>\n"
                    f"🎙️ Канал: <code>{voice_channel.guild.name} / #{voice_channel.name}</code>\n"
                    f"✅ Уже находился в этом канале"
                )
                return

        # Проверяем кулдаун на команды !call и !dota (5 минут)
        now = datetime.now()
        last_voice_cmd = self.voice_timestamps.get(user_id)
        if last_voice_cmd and now - last_voice_cmd < timedelta(minutes=5):
            seconds_left = int((last_voice_cmd + timedelta(minutes=5) - now).total_seconds())
            minutes = seconds_left // 60
            seconds = seconds_left % 60
            time_str = f"{minutes}м {seconds}с" if minutes > 0 else f"{seconds}с"
            await message.channel.send(f"⚠️ Команды !call и !dota доступны раз в 5 минут! Попробуй снова через {time_str}.")
            return

        # Отключаемся от текущего войса, если подключены к другому
        if self.voice_clients:
            for vc in self.voice_clients:
                await vc.disconnect(force=True)
            self.state.current_voice = None

        try:
            # Подключаемся с выключенным микрофоном. Отключаем reconnect, чтобы бот не
            # переподключался при входе с оригинального клиента.
            await voice_channel.connect(self_mute=True, self_deaf=False, reconnect=False)
            self.state.current_voice = f"{voice_channel.guild.name} / #{voice_channel.name}"
            
            # Сохраняем время успешного подключения
            self.voice_timestamps[user_id] = now

            # Формируем ответ
            if cmd_type == "dota":
                await message.channel.send(f"🎮 Иду в доту! Зашёл в **{voice_channel.name}** 🔇")
            else:
                await message.channel.send(f"👋 Зашёл в **{voice_channel.name}**! (микрофон выкл 🔇)")

            # Уведомление в Telegram
            await self.tg_notify(
                f"📩 <b>Новая команда!</b>\n"
                f"👤 От: <code>{username}</code>\n"
                f"💬 Команда: <code>!{cmd_type}</code>\n"
                f"🎙️ Канал: <code>{voice_channel.guild.name} / #{voice_channel.name}</code>\n"
                f"✅ Зашёл в войс (микрофон выкл)"
            )
        except Exception as e:
            await message.channel.send(f"❌ Не удалось подключиться: {e}")
            await self.tg_notify(
                f"❌ <b>Ошибка подключения к войсу</b>\n"
                f"👤 От: <code>{username}</code>\n"
                f"💬 Ошибка: <code>{e}</code>"
            )

    async def _handle_tg(self, message: discord.Message, username: str):
        """Обработка !tg — уведомление в Telegram."""
        user_id = message.author.id
        self.state.add_log(username, "!tg")

        if not self.state.is_active:
            if self._should_send_greeting(user_id):
                afk_msg = random.choice(config.AFK_MESSAGES)
                await message.channel.send(afk_msg)
                await self.tg_notify(
                    f"📩 <b>Команда в AFK-режиме</b>\n"
                    f"👤 От: <code>{username}</code>\n"
                    f"💬 Команда: <code>!tg</code>\n"
                    f"🔴 Ответил AFK-сообщением"
                )
            return

        # Проверяем лимит команды !tg
        allowed, seconds_left = self._check_tg_cooldown(user_id)
        if not allowed:
            minutes = seconds_left // 60
            seconds = seconds_left % 60
            time_str = f"{minutes}м {seconds}с" if minutes > 0 else f"{seconds}с"
            await message.channel.send(f"⚠️ Превышен лимит отправки уведомлений в Telegram! Разрешено максимум 3 раза за 5 минут. Попробуй снова через {time_str}.")
            return

        # Добавляем таймстамп успешной отправки
        self.tg_timestamps[user_id].append(datetime.now())

        await message.channel.send("✅ Отправил уведомление в Telegram! Скоро подойду.")
        await self.tg_notify(
            f"🔔 <b>Тебя ждут в Discord!</b>\n"
            f"👤 Пользователь: <code>{username}</code>\n"
            f"💬 Просит зайти!"
        )

    async def _handle_help(self, message: discord.Message, username: str):
        """Обработка !help — вывод списка команд."""
        user_id = message.author.id
        self.state.add_log(username, "!help")

        if not self.state.is_active:
            if self._should_send_greeting(user_id):
                afk_msg = random.choice(config.AFK_MESSAGES)
                reply_text = (
                    f"💤 {afk_msg}\n\n"
                    "🤖 **Я сейчас отошёл, но ты можешь использовать эти команды:**\n"
                    "• `!call` — Позвать меня в твой голосовой канал (зайду без микрофона 🔇)\n"
                    "• `!dota` — Позвать играть в доту (зайду в твой канал 🎮)\n"
                    "• `!tg` — Отправить мне уведомление в Telegram 🔔"
                )
                await message.channel.send(reply_text)
                await self.tg_notify(
                    f"📩 <b>Команда в AFK-режиме</b>\n"
                    f"👤 От: <code>{username}</code>\n"
                    f"💬 Команда: <code>!help</code>\n"
                    f"🔴 Ответил AFK-сообщением"
                )
            return

        help_text = (
            "👋 Привет! Я сейчас на связи. Доступные команды:\n"
            "• `!call` — Позвать меня в голосовой канал (я зайду с выключенным микрофоном 🔇)\n"
            "• `!dota` — Позвать играть в доту (зайду в твой канал 🎮)\n"
            "• `!tg` — Отправить мне уведомление в Telegram 🔔"
        )
        await message.channel.send(help_text)

    async def _handle_unknown(self, message: discord.Message, username: str):
        """Обработка любого неизвестного сообщения."""
        user_id = message.author.id
        if not self.state.is_active:
            if self._should_send_greeting(user_id):
                afk_msg = random.choice(config.AFK_MESSAGES)
                reply_text = (
                    f"💤 {afk_msg}\n\n"
                    "🤖 **Я сейчас не у компьютера, но ты можешь использовать эти команды:**\n"
                    "• `!call` — Позвать меня в твой голосовой канал (зайду без микрофона 🔇)\n"
                    "• `!dota` — Позвать играть в доту (зайду в твой канал 🎮)\n"
                    "• `!tg` — Отправить мне уведомление в Telegram 🔔"
                )
                await message.channel.send(reply_text)
                
                # Экранируем HTML-символы для отправки в TG
                esc_content = message.content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                await self.tg_notify(
                    f"📩 <b>Новое сообщение в ЛС (AFK)</b>\n"
                    f"👤 От: <code>{username}</code>\n"
                    f"💬 Текст: <code>{esc_content}</code>\n"
                    f"🔴 Ответил AFK-сообщением"
                )
            return

        # Если активен, подсказываем список команд (с КД 2 минуты)
        if self._should_send_greeting(user_id):
            reply_text = (
                "👋 Привет! Я сейчас на связи. Если ты хочешь позвать меня куда-то, используй эти команды:\n"
                "• `!call` — Позвать меня в голосовой канал (я зайду с выключенным микрофоном 🔇)\n"
                "• `!dota` — Позвать играть в доту (зайду в твой канал 🎮)\n"
                "• `!tg` — Отправить мне уведомление в Telegram 🔔"
            )
            await message.channel.send(reply_text)

    def _find_user_voice_channel(self, user_id: int) -> discord.VoiceChannel | None:
        """Ищем пользователя во всех голосовых каналах всех серверов."""
        for guild in self.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if member.id == user_id:
                        return vc
            # Также проверяем stage-каналы
            for sc in guild.stage_channels:
                for member in sc.members:
                    if member.id == user_id:
                        return sc
        return None

    async def disconnect_voice(self):
        """Отключиться от всех голосовых каналов."""
        disconnected = False
        for vc in self.voice_clients:
            await vc.disconnect(force=True)
            disconnected = True
        self.state.current_voice = None
        return disconnected

    async def play_audio_file(self, filepath: str, delete_after: bool = False) -> bool:
        """
        Воспроизводит локальный аудиофайл в текущем голосовом канале Discord.
        Возвращает True в случае успеха, False в случае неудачи.
        """
        import os

        # Находим активный войс клиент
        if not self.voice_clients:
            return False

        vc = self.voice_clients[0]
        if not vc.is_connected():
            return False

        try:
            # Если уже что-то проигрывается, останавливаем
            if vc.is_playing():
                vc.stop()

            # Проигрываем через FFmpeg
            source = discord.FFmpegPCMAudio(filepath)

            def cleanup(error):
                if error:
                    print(f"❌ Ошибка воспроизведения аудио: {error}")
                if delete_after:
                    try:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                    except Exception as e:
                        print(f"❌ Ошибка удаления временного файла: {e}")

            vc.play(source, after=cleanup)
            return True

        except Exception as e:
            print(f"❌ Ошибка воспроизведения аудиофайла: {e}")
            if delete_after:
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except:
                    pass
            return False

    async def play_tts(self, text: str, lang: str = "ru") -> bool:
        """
        Генерирует озвучку текста через gTTS и проигрывает в текущий войс-канал.
        Возвращает True в случае успеха, False в случае неудачи.
        """
        import uuid
        from gtts import gTTS

        # Путь к временному файлу
        temp_filename = f"/tmp/tts_{uuid.uuid4().hex}.mp3"

        try:
            # Генерация аудиофайла (в отдельном потоке, чтобы не блокировать event loop)
            def generate():
                tts = gTTS(text=text, lang=lang)
                tts.save(temp_filename)

            await asyncio.to_thread(generate)
            return await self.play_audio_file(temp_filename, delete_after=True)

        except Exception as e:
            print(f"❌ Ошибка генерации TTS: {e}")
            return False

    async def set_active(self, active: bool):
        """Включить или выключить активность бота (выход из войса)."""
        self.state.is_active = active
        if not active:
            await self.disconnect_voice()
            # Очищаем кэш стилей при выключении, чтобы при следующем уходе в AFK 
            # бот проанализировал свежую историю (с учётом новых ручных сообщений).
            self.user_styles.clear()

    async def _get_message_data(self, msg: discord.Message) -> tuple[str, dict | None]:
        """
        Возвращает кортеж (текст_сообщения, данные_картинки).
        данные_картинки имеет формат {"data": base64_str, "mime_type": str} или None.
        Если это голосовое сообщение, транскрибирует его.
        """
        text = msg.content or ""
        image_data = None

        # Проверяем вложения
        if msg.attachments:
            audio_att = None
            image_att = None
            
            for att in msg.attachments:
                filename_lower = att.filename.lower()
                
                # Проверка на аудио
                is_audio = (
                    filename_lower.endswith(('.ogg', '.wav', '.mp3', '.m4a', '.aac', '.mp4')) or
                    (att.content_type and att.content_type.startswith('audio/'))
                )
                if is_audio and not audio_att:
                    audio_att = att
                    continue
                    
                # Проверка на картинку
                is_image = (
                    filename_lower.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')) or
                    (att.content_type and att.content_type.startswith('image/'))
                )
                if is_image and not image_att:
                    image_att = att
                    continue
            
            # 1. Если нашли голосовое сообщение и нет текста
            if audio_att and not text:
                if msg.id in self.voice_transcripts:
                    text = f"[Голосовое сообщение]: {self.voice_transcripts[msg.id]}"
                else:
                    import uuid
                    import os
                    temp_name = f"/tmp/discord_voice_{uuid.uuid4().hex}.ogg"
                    try:
                        await audio_att.save(temp_name)
                        transcribed = await ai_helper.transcribe_audio(temp_name)
                        if transcribed:
                            self.voice_transcripts[msg.id] = transcribed
                            text = f"[Голосовое сообщение]: {transcribed}"
                        else:
                            text = "[Голосовое сообщение] (не удалось распознать)"
                    except Exception as e:
                        print(f"❌ Ошибка скачивания/распознавания ГС в Discord: {e}")
                        text = "[Голосовое сообщение]"
                    finally:
                        if os.path.exists(temp_name):
                            try:
                                os.remove(temp_name)
                            except:
                                pass
            
            # 2. Если нашли картинку
            if image_att:
                import uuid
                import os
                import base64
                # Определяем расширение
                ext = ".png"
                if image_att.filename:
                    _, file_ext = os.path.splitext(image_att.filename.lower())
                    if file_ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif']:
                        ext = file_ext
                
                temp_img = f"/tmp/discord_img_{uuid.uuid4().hex}{ext}"
                try:
                    await image_att.save(temp_img)
                    with open(temp_img, "rb") as f:
                        b64_data = base64.b64encode(f.read()).decode("utf-8")
                    
                    mime_type = image_att.content_type or f"image/{ext.lstrip('.')}"
                    if mime_type == "image/jpg":
                        mime_type = "image/jpeg"
                        
                    image_data = {
                        "data": b64_data,
                        "mime_type": mime_type
                    }
                    if not text:
                        text = "[Изображение]"
                except Exception as e:
                    print(f"❌ Ошибка скачивания/обработки изображения в Discord: {e}")
                finally:
                    if os.path.exists(temp_img):
                        try:
                            os.remove(temp_img)
                        except:
                            pass

        return text, image_data

    async def _respond_with_ai(self, message: discord.Message):
        """Интеграция ИИ для ответов в ЛС при отключенном боте с дебаунсом."""
        user_id = message.author.id
        username = str(message.author)

        try:
            # Задержка (дебаунс) в 2.5 секунды, чтобы дать пользователю дописать мысль
            await asyncio.sleep(2.5)

            # Отображаем статус "печатает" в Discord, пока работает ИИ
            async with message.channel.typing():
                start_time = asyncio.get_event_loop().time()
                recent_msgs = []
                now_utc = datetime.now(timezone.utc)

                # Загружаем до 30 сообщений истории, чтобы отфильтровать автоматические и получить 10 настоящих
                async for msg in message.channel.history(limit=30):
                    if len(recent_msgs) >= 10:
                        break
                    
                    msg_text, img_data = await self._get_message_data(msg)
                    if not msg_text and not img_data:
                        continue
                    if msg_text and self._is_auto_reply(msg_text):
                        continue
                    
                    time_ago = self._get_time_ago_str(msg.created_at, now_utc)
                    recent_msgs.append({
                        "is_self": msg.author.id == self.user.id,
                        "text": msg_text,
                        "image": img_data,
                        "time_ago": time_ago
                    })
                recent_msgs.reverse()

                # Если стиля общения еще нет в кэше
                if user_id not in self.user_styles:
                    # Запускаем фоновую задачу для анализа и кэширования стиля
                    asyncio.create_task(self._background_analyze_style(message, user_id, username))
                    
                    # Временный дефолтный стиль
                    system_instruction = (
                        "Ты — владелец этого аккаунта Discord (человек, парень). Тебе пишет твой знакомый или друг.\n"
                        "Твоя задача — написать ответ собеседнику от первого лица.\n"
                        "Отвечай максимально коротко (1-4 слова), в простом разговорном тоне, строчными буквами без знаков препинания в конце.\n"
                        "Не пиши длинные сообщения без необходимости, без воды, и никогда не повторяй одну и ту же букву или слово (никаких 'аааааа').\n"
                        "КРИТИЧЕСКИ ВАЖНО: Ты человек, а не ИИ. Никаких формальностей, вежливых клише, смайликов и упоминаний ИИ/ботов.\n"
                        "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять в свой ответ любые временные метки вроде '[только что]', '[5 мин. назад]' и т.д.\n"
                        "Отвечай ОДНИМ сообщением в ОДНУ строку. НЕ переноси строки и не разбивай ответ на несколько строк/сообщений."
                    )
                else:
                    system_instruction = (
                        f"Ты — владелец этого аккаунта Discord (человек, парень). Тебе пишет твой знакомый или друг.\n"
                        f"Твоя задача — написать ответ собеседнику от первого лица, точно копируя свой стиль общения с ним.\n\n"
                        f"Описание твоего стиля общения с этим собеседником:\n{self.user_styles[user_id]}\n\n"
                        f"КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА:\n"
                        f"1. Ты НЕ ИИ, НЕ бот, НЕ виртуальный ассистент. Ты человек. Не используй вежливые фразы, предупреждения и не пиши про ограничения.\n"
                        f"2. Полностью зеркаль уровень агрессии, токсичности и лексику собеседника:\n"
                        f"   - Если он дружелюбен — будь дружелюбен.\n"
                        f"   - Если он матерится, агрессирует, наезжает или оскорбляет тебя (использует слова вроде 'уебан', 'мразь' и т.д.) — отвечай ВЗАИМНО ЖЕСТКО, грубо и с матом (например: 'сам ты мразь', 'ебальник прикрой', 'завали ебало', 'пошел нахуй'). Отвечай один в один по уровню токсичности. Не пиши детские отмазки вроде 'сам такой' and не добавляй смайлики вроде '🔇', если тебя оскорбляют.\n"
                        f"3. Отвечай максимально коротко (1-4 слова, максимум одно короткое предложение), как при реальной перепалке.\n"
                        f"   - Не пиши длинные сообщения без необходимости, без воды, и никогда не повторяй одну и ту же букву или слово (никаких 'аааааа').\n"
                        f"4. Соблюдай особенности письма: пиши строчными буквами без знаков препинания в конце, если это твой привычный стиль.\n"
                        f"5. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять в свой ответ любые временные метки в квадратных скобках (например, '[только что]', '[5 мин. назад]').\n"
                        f"6. Отвечай ОДНИМ сообщением в ОДНУ строку. НЕ переноси строки и не разбивай ответ на несколько строк/сообщений."
                    )

                reply_text = await ai_helper.generate_response(system_instruction, recent_msgs)

                # Получаем/транскрибируем входящее сообщение для уведомлений Telegram
                incoming_text, incoming_image = await self._get_message_data(message)

                # Отправляем ответ и уведомляем владельца в Telegram
                if reply_text:
                    generation_time = asyncio.get_event_loop().time() - start_time
                    # Симуляция скорости печатания человека: от 5 до 9 символов в секунду
                    typing_speed = random.uniform(5.0, 9.0)
                    required_typing_time = len(reply_text) / typing_speed
                    # Ограничиваем максимальное время печатания 8 секундами
                    required_typing_time = min(required_typing_time, 8.0)
                    
                    remaining_typing_time = required_typing_time - generation_time
                    if remaining_typing_time > 0:
                        await asyncio.sleep(remaining_typing_time)
                        
                    await message.channel.send(reply_text)
                    self.state.add_log(username, "ИИ-ответ")
                    
                    # Экранируем HTML-символы для Telegram панели
                    esc_reply = reply_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    esc_incoming = incoming_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    if incoming_image:
                        esc_incoming = f"🖼️ [Изображение] {esc_incoming}"
                        
                    await self.tg_notify(
                        f"🤖 <b>ИИ ответил за вас в Discord!</b>\n"
                        f"👤 Собеседник: <code>{username}</code>\n"
                        f"💬 Сообщение: <i>{esc_incoming}</i>\n"
                        f"✍️ Ответ ИИ: <b>{esc_reply}</b>"
                    )
                else:
                    # Фолбэк на обычное AFK-сообщение при сбое ИИ (например, лимит запросов)
                    print(f"⚠️ ИИ не смог сгенерировать ответ для {username}. Используем AFK-фолбэк.")
                    if self._should_send_greeting(user_id):
                        afk_msg = random.choice(config.AFK_MESSAGES)
                        await message.channel.send(afk_msg)
                        
                        esc_incoming = incoming_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        if incoming_image:
                            esc_incoming = f"🖼️ [Изображение] {esc_incoming}"
                            
                        await self.tg_notify(
                            f"📩 <b>AFK-фолбэк (сбой ИИ)</b>\n"
                            f"👤 От: <code>{username}</code>\n"
                            f"💬 Сообщение: <i>{esc_incoming}</i>\n"
                            f"🔴 Ответил AFK-сообщением из-за лимита/ошибки ИИ"
                        )
        except asyncio.CancelledError:
            # Ожидаемый случай при перебивании новыми сообщениями
            print(f"ℹ️ Автоответ для {username} отменен новым сообщением (дебаунс).")
        except Exception as e:
            print(f"❌ Ошибка в ИИ-автоответчике: {e}")
        finally:
            # Удаляем задачу из словаря active_tasks, если она текущая
            if self.ai_tasks.get(user_id) == asyncio.current_task():
                self.ai_tasks.pop(user_id, None)

    async def _background_analyze_style(self, message: discord.Message, user_id: int, username: str):
        """Фоновый анализ стиля по последним 500 сообщениям чата."""
        try:
            print(f"⚙️ Фоновый анализ: анализирую историю общения с {username} для создания стиля (лимит 500)...")
            history_msgs = []
            async for msg in message.channel.history(limit=500):
                if msg.content:
                    if self._is_auto_reply(msg.content):
                        continue

                    history_msgs.append({
                        "is_self": msg.author.id == self.user.id,
                        "text": msg.content
                    })
            history_msgs.reverse()

            if history_msgs:
                style = await ai_helper.analyze_style(history_msgs, self.user.name)
                self.user_styles[user_id] = style
                print(f"✨ Создан профиль стиля для {username} (в фоне):\n{style}\n")
            else:
                self.user_styles[user_id] = "Отвечай коротко, просто, дружелюбно."
        except Exception as e:
            print(f"❌ Ошибка фонового анализа стиля для {username}: {e}")
