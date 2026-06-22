# 🎮 Discord Self-Bot + Telegram Панель Управления

Self-bot для Discord, управляемый через красивый Telegram интерфейс.

## ⚡ Возможности

- **`!call`** — автоматический заход в голосовой канал к отправителю (микрофон выкл)
- **`!dota`** — то же + сообщение «Иду в доту!»
- **`!tg`** — уведомление в Telegram что тебя ждут
- **🟢/🔴 Вкл/Выкл** — через Telegram с красивыми кнопками
- **📊 Статус** — текущее состояние бота, войса, uptime
- **📝 Логи** — история последних команд
- **🔌 Выход из войса** — одной кнопкой

## 📋 Требования

- Python 3.10+
- Системные пакеты для голоса: `libffi-dev`, `libnacl-dev`, `ffmpeg`

## 🛠️ Установка

### 1. Клонирование и настройка

```bash
cd /home/ila/dsbot

# Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Устанавливаем зависимости
pip install -r requirements.txt
```

### 2. Системные пакеты (для голоса)

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install libffi-dev libnacl-dev ffmpeg

# CentOS / RHEL
sudo yum install libffi-devel libsodium-devel ffmpeg
```

### 3. Настройка `.env`

```bash
cp .env.example .env
nano .env
```

Заполни:
- `DISCORD_TOKEN` — токен аккаунта Discord
- `TELEGRAM_BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather)
- `TELEGRAM_CHAT_ID` — твой ID из [@userinfobot](https://t.me/userinfobot)

### 4. Запуск

```bash
python bot.py
```

## 🖥️ Деплой на VPS

### Автозапуск через systemd

```bash
sudo nano /etc/systemd/system/dsbot.service
```

Вставь:

```ini
[Unit]
Description=Discord Self-Bot + Telegram Panel
After=network.target

[Service]
Type=simple
User=ila
WorkingDirectory=/home/ila/dsbot
ExecStart=/home/ila/dsbot/venv/bin/python bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Активируй:

```bash
# Перечитать конфиги
sudo systemctl daemon-reload

# Включить автозапуск
sudo systemctl enable dsbot

# Запустить
sudo systemctl start dsbot

# Проверить статус
sudo systemctl status dsbot

# Логи
journalctl -u dsbot -f
```

### Управление сервисом

```bash
sudo systemctl start dsbot    # Запустить
sudo systemctl stop dsbot     # Остановить
sudo systemctl restart dsbot  # Перезапустить
sudo systemctl status dsbot   # Статус
```

---

### Автозапуск через PM2

Конфиг уже создан — [ecosystem.config.json](ecosystem.config.json).

```bash
# 1. Установи PM2 (если ещё нет)
npm install -g pm2

# 2. Запусти бота
cd /home/ila/dsbot
pm2 start ecosystem.config.json

# 3. Сохрани список процессов + автозапуск при ребуте
pm2 save
pm2 startup
```

#### Управление через PM2

```bash
pm2 start dsbot       # Запустить
pm2 stop dsbot        # Остановить
pm2 restart dsbot     # Перезапустить
pm2 status            # Список процессов
pm2 logs dsbot        # Логи в реальном времени
pm2 logs dsbot --lines 100  # Последние 100 строк
pm2 monit             # Мониторинг CPU/RAM
pm2 delete dsbot      # Удалить из PM2
```

## 🔑 Как получить Discord Token

1. Открой Discord в браузере (discord.com/app)
2. Нажми `F12` → вкладка `Network`
3. Отфильтруй по `api`
4. Найди любой запрос и посмотри заголовок `Authorization`
5. Скопируй значение — это твой токен

⚠️ **Никому не передавай свой токен!**

## ⚠️ Disclaimer

Self-боты нарушают Terms of Service Discord. Используй на свой страх и риск.
Аккаунт может быть заблокирован.
