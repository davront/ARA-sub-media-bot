# Создание тг бота для проверки подписки
_Exported on 8/12/2025 at 11:51:14 GMT+5 from Cursor (1.2.4)_

---

**User**

нужен тг бот!
 тз такого, если чел хочет присоединиться в группу, то ему нужно сначала подписаться на канал, получается тг бот будет будет проверять подписан ли человек на канал и после этого впускать в группу

---

**Cursor**

План: создам рабочий каркас бота на Python (aiogram 3) с обработкой join-request и новых участников, проверкой подписки через getChatMember, командами /start и /check, и инструкциями по запуску. Затем добавлю зависимости и README. Далее можно будет запустить у вас локально.

Приступаю к созданию файлов.

```python
import asyncio
import logging
import os
import time
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ChatJoinRequest

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")
CHANNEL_ID_RAW: Optional[str] = os.getenv("CHANNEL_ID")  # e.g. -1001234567890 or @my_channel
GROUP_ID_RAW: Optional[str] = os.getenv("GROUP_ID")  # e.g. -1001234567890
CHANNEL_LINK: Optional[str] = os.getenv("CHANNEL_LINK")  # e.g. https://t.me/my_channel


def parse_chat_id(id_raw: Optional[str]) -> Optional[int | str]:
    if not id_raw:
        return None
    id_raw = id_raw.strip()
    # For public channels usernames like @my_channel we keep as string
    if id_raw.startswith("@"):
        return id_raw
    # Numeric IDs (may come as string)
    try:
        return int(id_raw)
    except ValueError:
        return id_raw


CHANNEL_ID = parse_chat_id(CHANNEL_ID_RAW)
GROUP_ID = parse_chat_id(GROUP_ID_RAW)


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Put it in environment or .env file.")
if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID is not set. Use channel @username or numeric ID (e.g. -100...).")


router = Router()


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        status = getattr(member, "status", None)
        return status in ("member", "administrator", "creator")
    except Exception as e:
        logging.warning("get_chat_member failed for user %s: %s", user_id, e)
        return False


@router.chat_join_request()
async def on_chat_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    if GROUP_ID is not None and event.chat.id != GROUP_ID:
        return

    user_id = event.from_user.id
    if await is_user_subscribed(bot, user_id):
        await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=user_id)
    else:
        await bot.decline_chat_join_request(chat_id=event.chat.id, user_id=user_id)
        # Try to notify user in DM (may fail if user never started the bot)
        if CHANNEL_LINK:
            text = (
                "Чтобы попасть в группу, сначала подпишитесь на канал: "
                f"{CHANNEL_LINK}\nПосле подписки вернитесь и снова отправьте заявку."
            )
        else:
            text = (
                "Чтобы попасть в группу, сначала подпишитесь на обязательный канал. "
                "После подписки вернитесь и снова отправьте заявку."
            )
        try:
            await bot.send_message(user_id, text)
        except Exception:
            pass


@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message, bot: Bot) -> None:
    if GROUP_ID is not None and message.chat.id != GROUP_ID:
        return

    # Clean up service message regardless of outcome
    try:
        await message.delete()
    except Exception:
        pass

    if not message.new_chat_members:
        return

    for user in message.new_chat_members:
        user_id = user.id
        subscribed = await is_user_subscribed(bot, user_id)
        if subscribed:
            continue
        # Kick non-subscribed user (ban+unban trick to remove immediately)
        try:
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=user_id, until_date=int(time.time()) + 30)
            await bot.unban_chat_member(chat_id=message.chat.id, user_id=user_id, only_if_banned=True)
        except Exception as e:
            logging.warning("Failed to remove non-subscribed user %s: %s", user_id, e)
        # Try to DM instructions
        if CHANNEL_LINK:
            info = (
                "Доступ в группу только для подписчиков канала: "
                f"{CHANNEL_LINK}\nПодпишитесь и попробуйте снова."
            )
        else:
            info = (
                "Доступ в группу только для подписчиков обязательного канала. "
                "Подпишитесь и попробуйте снова."
            )
        try:
            await bot.send_message(user_id, info)
        except Exception:
            pass


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    lines = [
        "Привет! Я проверяю подписку на канал перед вступлением в группу.",
    ]
    if CHANNEL_LINK:
        lines.append(f"Сначала подпишитесь на канал: {CHANNEL_LINK}")
    if GROUP_ID is not None:
        lines.append("После подписки отправьте заявку на вступление через ссылку группы.")
    await message.answer("\n".join(lines))


@router.message(Command("check"))
async def on_check(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    subscribed = await is_user_subscribed(bot, user_id)
    if not subscribed:
        if CHANNEL_LINK:
            await message.answer(
                f"Вы ещё не подписаны. Подпишитесь: {CHANNEL_LINK} и повторите команду /check."
            )
        else:
            await message.answer("Вы ещё не подписаны на обязательный канал. Подпишитесь и повторите /check.")
        return

    if GROUP_ID is None:
        await message.answer("Проверка пройдена. Обратитесь к администратору за ссылкой в группу.")
        return

    try:
        invite = await bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            creates_join_request=True,
            name=f"verify_{user_id}_{int(time.time())}",
            expires_in=3600,
            member_limit=1,
        )
        await message.answer(
            "Подписка подтверждена. Подавайте заявку на вступление по ссылке (действует 1 час, одно использование):\n"
            f"{invite.invite_link}"
        )
    except Exception as e:
        logging.error("Failed to create invite link: %s", e)
        await message.answer(
            "Подписка подтверждена, но не удалось создать ссылку приглашения. "
            "Попросите администратора добавить вас или проверьте права бота в группе."
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bot = Bot(BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher()
    dp.include_router(router)

    # Drop pending updates to avoid mass-approvals on first run
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

```

```pip-requirements
aiogram>=3.4.1
python-dotenv>=1.0.1

```

```markdown
# Бот для проверки подписки перед вступлением в группу

Функции:
- При заявке на вступление в группу бот проверяет, подписан ли пользователь на канал. Если да — одобряет, иначе — отклоняет и присылает инструкцию в ЛС.
- Если кто-то попадает в группу без заявки (инвайт и т.п.), бот проверяет подписку и удаляет нарушителей.
- Команды `/start` и `/check`. `/check` выдаёт персональную ссылку-заявку, если подписка есть.

## Требования
- Python 3.10+
- Токен бота из @BotFather
- Канал (публичный `@username` или ID `-100...`) и группа (ID `-100...`)

## Установка
```bash
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Настройка переменных окружения
Создайте файл `.env` рядом с `main.py`:
```env
BOT_TOKEN=123456789:AA...
CHANNEL_ID=@your_channel  # или -1001234567890
GROUP_ID=-1001234567890   # ID вашей группы (по желанию можно не указывать для режима только проверки)
CHANNEL_LINK=https://t.me/your_channel
```
Примечания:
- `CHANNEL_ID` — обязательный. Можно указать `@username` (для публичного канала) или числовой ID `-100...` (для приватного).
- `GROUP_ID` — рекомендуется указать, чтобы слушать заявки именно этой группы.
- `CHANNEL_LINK` — ссылка для подсказок пользователю.

## Права бота
Добавьте бота админом:
- В канале: достаточно права видеть подписчиков (для приватного канала — бот должен быть админом/редактором).
- В группе: обязательно «Добавление участников через заявки», «Бан участников», «Удаление сообщений», «Приглашение по ссылкам».

## Настройка группы (join requests)
- Включите «Одобрение заявок» в настройках группы.
- Используйте ссылки с параметром «Требовать одобрение».

## Запуск
```bash
python main.py
```

## Проверка
1. Нажмите `/start` боту, чтобы он мог писать вам в ЛС.
2. Подпишитесь на канал.
3. Введите `/check` — если подписка ок, получите персональную ссылку-заявку.
4. Подавайте заявку — бот автоматически одобрит.

## Частые вопросы
- Бот не пишет в ЛС: пользователь должен сначала нажать «Start» в личке с ботом.
- Приватный канал: используйте ID `-100...` и добавьте бота в администраторы канала.
- Ошибка при создании инвайта: проверьте, что бот админ в группе и включены права на «Приглашение по ссылкам».

```

Сделал первый проход: создал каркас бота `main.py` (aiogram 3) с проверкой подписки на канал при заявке в группу и при входе, добавил `requirements.txt` и русскоязычный `README.md`. Сейчас добавлю пример `.env`, затем предложу команды для установки и запуска у вас на Windows.

Сейчас установлю зависимости в виртуальном окружении и создам шаблон `.env` в вашей папке проекта. Затем дам краткие шаги по настройке прав в Telegram и запуску.

```plaintext
.\.venv\Scripts\Activate.ps1 
python main.py
```

```plaintext
notepad .env
.\.venv\Scripts\Activate.ps1
python main.py
```

Сделал каркас бота и окружение. Код `main.py` (aiogram 3) обрабатывает заявки на вступление, проверяет подписку на канал и автоматически одобряет/отклоняет. Добавлены `requirements.txt` и `README.md`. Создал `.env` с плейсхолдерами — осталось заполнить.

### Что сделать в Telegram
- Добавьте бота админом в канал (лучше редактором) и в группу.
- В группе включите «Одобрение заявок».
- Дайте боту в группе права: приглашать по ссылкам, одобрять заявки, банить пользователей, удалять сообщения.

### Настройка .env
Откройте файл и заполните:
```bash
notepad .env
```
- BOT_TOKEN=токен из @BotFather
- CHANNEL_ID=@username канала или -100идентификатор (для приватного — только -100… и бот должен быть админом)
- GROUP_ID=-100идентификатор вашей группы
- CHANNEL_LINK=https://t.me/username канала

Как получить ID:
- Группа/канал: перешлите любое сообщение в бота `@userinfobot` или `@RawDataBot`.

### Запуск
```bash
. .\.venv\Scripts\Activate.ps1
python main.py
```

Проверка:
- Откройте личный диалог с ботом, нажмите Start.
- Подпишитесь на канал.
- Введите команду `/check` — получите персональную ссылку-заявку.
- Подайте заявку — бот одобрит, если подписка есть.
- Если кто-то попадёт в группу без заявки — бот проверит подписку и удалит нарушителей.

Если потребуется — могу сразу помочь заполнить `.env` (пришлите токен/ID), и проверить права в канале/группе.

- Создал `main.py` с обработкой ChatJoinRequest и проверкой подписки через `getChatMember`; добавил `/start` и `/check`.
- Добавил `requirements.txt`, `README.md`, установил зависимости и сгенерировал `.env` с плейсхолдерами.
- Готово к запуску: отредактируйте `.env`, дайте боту нужные права и запустите.

```shellscript
notepad .env
```

```shellscript
. .\.venv\Scripts\Activate.ps1
python main.py
```

---

**User**

напиши мне  что требуется для  заказчика, типо название бота, нахвание канала , группы

---

**Cursor**

### Что нужно получить от заказчика (бриф)

- Обязательное
  - BOT_TOKEN: токен бота из `@BotFather`
  - Название бота и `@username` бота
  - Канал: ссылка `https://t.me/...` и `@username` или ID `-100...`
  - Группа: ссылка-приглашение и ID `-100...` (супергруппа)
- Настройки в Telegram
  - Бот добавлен админом в канал (для приватного канала — обязателен)
  - Бот добавлен админом в группу
  - В группе включены «Заявки на вступление» (требуется одобрение)
- Тексты и правила
  - Текст приветствия (/start)
  - Текст при отказе: что писать, если нет подписки (ссылку на канал)
  - Нужно ли выдавать персональную ссылку через /check (срок действия, лимит 1 использование — ок?)
- Дополнительно (по желанию)
  - Логотип/аватар бота, описание
  - Список админов (их user ID) для тестов/поддержки
  - Где хостить бота (у заказчика/VPS), часовой пояс работы
  - Критерии приёмки: как проверяем (кейсы: подписан/не подписан, приватный/публичный канал)

Если дадите ссылку на канал/группу и токен, я сам получу нужные ID и проверю права.

