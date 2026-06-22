"""Discord Self-Bot — обработка команд !call, !dota, !tg в личных сообщениях."""

import random
import asyncio
from datetime import datetime

import discord

import config


class DiscordSelfBot(discord.Client):
    """Self-bot клиент Discord с обработкой DM-команд."""

    def __init__(self, bot_state, telegram_notify_func):
        # Минимальные интенты — нужны guilds, voice_states, dm_messages
        super().__init__()
        self.state = bot_state
        self.tg_notify = telegram_notify_func

    async def on_ready(self):
        print(f"✅ Discord: залогинен как {self.user} (ID: {self.user.id})")
        self.state.discord_username = str(self.user)
        self.state.discord_ready = True

        # Уведомляем в Telegram о запуске
        await self.tg_notify(
            "🟢 *Discord Self-Bot запущен!*\n"
            f"👤 Аккаунт: `{self.user}`\n"
            f"🌐 Серверов: `{len(self.guilds)}`"
        )

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

        # Проверяем команды
        if content == "!call":
            await self._handle_call(message, username, user_id, "call")
        elif content == "!dota":
            await self._handle_call(message, username, user_id, "dota")
        elif content == "!tg":
            await self._handle_tg(message, username)

    async def _handle_call(self, message: discord.Message, username: str, user_id: int, cmd_type: str):
        """Обработка !call и !dota — заход в войс к отправителю."""
        # Логируем
        self.state.add_log(username, f"!{cmd_type}")

        # Если бот выключен — AFK ответ
        if not self.state.is_active:
            afk_msg = random.choice(config.AFK_MESSAGES)
            await message.channel.send(afk_msg)
            await self.tg_notify(
                f"📩 *Команда в AFK-режиме*\n"
                f"👤 От: `{username}`\n"
                f"💬 Команда: `!{cmd_type}`\n"
                f"🔴 Ответил AFK-сообщением"
            )
            return

        # Ищем пользователя в голосовых каналах
        voice_channel = self._find_user_voice_channel(user_id)

        if not voice_channel:
            await message.channel.send("❌ Ты не в голосовом канале! Зайди в войс и попробуй снова.")
            await self.tg_notify(
                f"📩 *Новая команда*\n"
                f"👤 От: `{username}`\n"
                f"💬 Команда: `!{cmd_type}`\n"
                f"⚠️ Пользователь не в голосовом канале"
            )
            return

        # Отключаемся от текущего войса, если подключены
        if self.voice_clients:
            for vc in self.voice_clients:
                await vc.disconnect(force=True)
            self.state.current_voice = None

        try:
            # Подключаемся с выключенным микрофоном
            await voice_channel.connect(self_mute=True, self_deaf=False)
            self.state.current_voice = f"{voice_channel.guild.name} / #{voice_channel.name}"

            # Формируем ответ
            if cmd_type == "dota":
                await message.channel.send(f"🎮 Иду в доту! Зашёл в **{voice_channel.name}** 🔇")
            else:
                await message.channel.send(f"👋 Зашёл в **{voice_channel.name}**! (микрофон выкл 🔇)")

            # Уведомление в Telegram
            await self.tg_notify(
                f"📩 *Новая команда!*\n"
                f"👤 От: `{username}`\n"
                f"💬 Команда: `!{cmd_type}`\n"
                f"🎙️ Канал: `{voice_channel.guild.name} / #{voice_channel.name}`\n"
                f"✅ Зашёл в войс (микрофон выкл)"
            )
        except Exception as e:
            await message.channel.send(f"❌ Не удалось подключиться: {e}")
            await self.tg_notify(
                f"❌ *Ошибка подключения к войсу*\n"
                f"👤 От: `{username}`\n"
                f"💬 Ошибка: `{e}`"
            )

    async def _handle_tg(self, message: discord.Message, username: str):
        """Обработка !tg — уведомление в Telegram."""
        self.state.add_log(username, "!tg")

        if not self.state.is_active:
            afk_msg = random.choice(config.AFK_MESSAGES)
            await message.channel.send(afk_msg)
            await self.tg_notify(
                f"📩 *Команда в AFK-режиме*\n"
                f"👤 От: `{username}`\n"
                f"💬 Команда: `!tg`\n"
                f"🔴 Ответил AFK-сообщением"
            )
            return

        await message.channel.send("✅ Отправил уведомление в Telegram! Скоро подойду.")
        await self.tg_notify(
            f"🔔 *Тебя ждут в Discord!*\n"
            f"👤 Пользователь: `{username}`\n"
            f"💬 Просит зайти!"
        )

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
