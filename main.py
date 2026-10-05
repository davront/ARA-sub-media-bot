import asyncio
import html
import logging
import os
import time
from datetime import timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatJoinRequest,
    ChatPermissions,
    EphemeralMessageParameters,
    InlineKeyboardMarkup,
    Message,
    User,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# Support TOKEN (preferred) with fallback to BOT_TOKEN for compatibility
BOT_TOKEN: Optional[str] = os.getenv("TOKEN") or os.getenv("BOT_TOKEN")
CHANNEL_ID_RAW: Optional[str] = os.getenv("CHANNEL_ID")  # e.g. -1001234567890 or @my_channel
GROUP_ID_RAW: Optional[str] = os.getenv("GROUP_ID")  # e.g. -1001234567890
CHANNEL_LINK: Optional[str] = os.getenv("CHANNEL_LINK")  # e.g. https://t.me/my_channel

MAX_RETRIES = 3  # Попытки при flood control (429)
# Telegram считает мут короче 30 сек или длиннее 366 дней вечным — держать в этих рамках
MUTE_SECONDS = 60


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
    raise RuntimeError("TOKEN/BOT_TOKEN is not set. Put it in environment or .env file.")
if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID is not set. Use channel @username or numeric ID (e.g. -100...).")

# Ссылка t.me/c/<id> открывается только участникам канала, поэтому для числового ID нужен CHANNEL_LINK
if CHANNEL_LINK:
    CHANNEL_URL: Optional[str] = CHANNEL_LINK
elif isinstance(CHANNEL_ID, str) and CHANNEL_ID.startswith("@"):
    CHANNEL_URL = f"https://t.me/{CHANNEL_ID[1:]}"
else:
    CHANNEL_URL = None


router = Router()

# (chat_id, user_id) -> time.monotonic(), до которого действует мут, выставленный ботом.
# Кнопка «Men obuna bo'ldim» снимает только такие муты, ручные муты админов не трогает.
BOT_MUTED: dict[tuple[int, int], float] = {}


def muted_by_bot(chat_id: int, user_id: int) -> bool:
    return BOT_MUTED.get((chat_id, user_id), 0) > time.monotonic()


def display_name(user: User) -> str:
    """Имя пользователя, безопасное для parse_mode=HTML."""
    if user.username:
        return f"@{user.username}"
    name = user.first_name or "Foydalanuvchi"
    if user.last_name:
        name += f" {user.last_name}"
    return html.escape(name)


def mention(user: User) -> str:
    return f'<a href="tg://user?id={user.id}">{display_name(user)}</a>'


def is_our_channel(chat: Chat) -> bool:
    if chat.id == CHANNEL_ID:
        return True
    return bool(chat.username) and f"@{chat.username}".lower() == str(CHANNEL_ID).lower()


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> Optional[Message]:
    """send_message с повтором только при flood control; остальные ошибки повторять бессмысленно."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except TelegramRetryAfter as e:
            logging.warning(f"⚠️ Flood control для чата {chat_id}, попытка {attempt}/{MAX_RETRIES}, ждем {e.retry_after} сек")
            await asyncio.sleep(e.retry_after + 1)
        except Exception as e:
            logging.error(f"❌ Ошибка отправки сообщения в чат {chat_id}: {e}")
            return None
    logging.error(f"❌ Не удалось отправить сообщение в чат {chat_id} после {MAX_RETRIES} попыток")
    return None


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        # Ошибка тут почти всегда = бот не админ канала. Пропускаем, а не мутим всю группу.
        logging.error(f"❌ Не удалось проверить подписку user_id={user_id} (бот админ в канале?): {e}")
        return True


async def mute_user(bot: Bot, chat_id: int, user_id: int) -> None:
    # until_date: Telegram сам снимет мут, даже если бот перезапустится
    permissions = ChatPermissions(**{field: False for field in ChatPermissions.model_fields})
    await bot.restrict_chat_member(
        chat_id=chat_id, user_id=user_id, permissions=permissions,
        until_date=timedelta(seconds=MUTE_SECONDS),
    )
    BOT_MUTED[(chat_id, user_id)] = time.monotonic() + MUTE_SECONDS


async def unmute_user(bot: Bot, chat_id: int, user_id: int) -> None:
    # Ограничение снимается только если передать True для всех разрешений
    permissions = ChatPermissions(**{field: True for field in ChatPermissions.model_fields})
    await bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=permissions)
    BOT_MUTED.pop((chat_id, user_id), None)


async def delete_message_after(bot: Bot, chat_id: int, message_id: int, delay_seconds: int) -> None:
    try:
        await asyncio.sleep(delay_seconds)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logging.warning(f"⚠️ Не удалось удалить сообщение {message_id}: {e}")


def subscribed_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if CHANNEL_URL:
        kb.button(text="📺 Obuna bo'lish", url=CHANNEL_URL)
    kb.button(text="✅ Men obuna bo'ldim", callback_data="i_subscribed")
    kb.adjust(1)
    return kb.as_markup()


async def send_notice(bot: Bot, chat_id: int, user: User, text: str) -> None:
    """Подсказка с кнопками, видимая только user (ephemeral). Если API отказал — публичная на 60 сек."""
    sent = await safe_send(
        bot, chat_id, text,
        reply_markup=subscribed_keyboard(),
        ephemeral_message_parameters=EphemeralMessageParameters(receiver_user_id=user.id),
    )
    if sent:
        return
    sent = await safe_send(bot, chat_id, text, reply_markup=subscribed_keyboard())
    if sent:
        asyncio.create_task(delete_message_after(bot, chat_id, sent.message_id, MUTE_SECONDS))


# media_group_id -> message_id частей альбома: Telegram присылает альбом отдельными апдейтами
ALBUMS: dict[str, list[int]] = {}


@router.channel_post()
async def on_channel_post(message: Message, bot: Bot) -> None:
    """Новый пост канала пересылаем в группу."""
    if GROUP_ID is None or not is_our_channel(message.chat):
        return

    if message.media_group_id:
        album = ALBUMS.setdefault(message.media_group_id, [])
        album.append(message.message_id)
        if len(album) > 1:
            return  # пересылкой займется обработчик первой части
        # ponytail: ждем остальные части фиксированную секунду; если альбомы рвутся — увеличить
        await asyncio.sleep(1)
        message_ids = sorted(ALBUMS.pop(message.media_group_id))
    else:
        message_ids = [message.message_id]

    try:
        await bot.forward_messages(chat_id=GROUP_ID, from_chat_id=message.chat.id, message_ids=message_ids)
        logging.info(f"📤 Пост канала {message_ids} переслан в группу {GROUP_ID}")
    except Exception as e:
        # Например, в канале включен запрет пересылки (protected content)
        logging.error(f"❌ Не удалось переслать пост {message_ids} в группу: {e}")


@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message, bot: Bot) -> None:
    if GROUP_ID is not None and message.chat.id != GROUP_ID:
        return

    # Удаляем сервисное сообщение о присоединении
    try:
        await message.delete()
    except Exception as e:
        logging.warning(f"⚠️ Не удалось удалить сервисное сообщение о присоединении: {e}")

    for user in message.new_chat_members:
        if user.is_bot:
            continue
        logging.info(f"👤 Новый участник user_id={user.id} в чате {message.chat.id}")
        if await is_user_subscribed(bot, user.id):
            continue
        text = (
            f"🔔 Yangi ishtirokchi!\n\n"
            f"👤 {mention(user)}\n"
            f"✍️ Guruhda yozish uchun kanalga obuna bo'ling.\n\n"
            f"Obuna bo'lgach, \"✅ Men obuna bo'ldim\" tugmasini bosing."
        )
        await send_notice(bot, message.chat.id, user, text)


# Должен стоять раньше общего @router.message(): aiogram берет первый подходящий обработчик
@router.message(F.left_chat_member)
async def on_left_chat_member(message: Message) -> None:
    if GROUP_ID is not None and message.chat.id != GROUP_ID:
        return
    try:
        await message.delete()
    except Exception as e:
        logging.warning(f"⚠️ Не удалось удалить системное сообщение о выходе/удалении: {e}")


@router.chat_join_request()
async def on_chat_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    if GROUP_ID is not None and event.chat.id != GROUP_ID:
        return

    user_id = event.from_user.id
    if await is_user_subscribed(bot, user_id):
        logging.info(f"✅ Запрос на вступление {user_id} принят")
        try:
            await event.approve()
        except Exception as e:
            logging.error(f"❌ Не удалось принять запрос {user_id}: {e}")
        return

    channel_step = f"Linkni bosing: {CHANNEL_URL}" if CHANNEL_URL else "Kanalga obuna bo'ling"
    text = (
        f"🔴 DIQQAT! Sizning kirish so'rovingiz rad etildi!\n\n"
        f"👤 {display_name(event.from_user)}, guruhga kirish uchun:\n\n"
        f"1️⃣ {channel_step}\n"
        f"2️⃣ \"Obuna bo'lish\" / \"Join\" tugmasini bosing\n"
        f"3️⃣ Guruhga qayting va yangi so'rov yuboring\n\n"
        f"💡 Obuna bo'lgandan so'ng so'rov avtomatik qabul qilinadi!"
    )
    # Писать по user_chat_id можно только пока заявка не обработана, поэтому до decline
    try:
        await event.answer_pm(text)
    except Exception as e:
        logging.warning(f"⚠️ Не удалось отправить сообщение пользователю {user_id}: {e}")
    try:
        await event.decline()
        logging.info(f"❌ Запрос на вступление {user_id} отклонен")
    except Exception as e:
        logging.error(f"❌ Не удалось отклонить запрос {user_id}: {e}")


@router.callback_query(F.data == "i_subscribed")
async def on_subscribed_click(callback: CallbackQuery, bot: Bot) -> None:
    msg = callback.message
    if msg is None or (GROUP_ID is not None and msg.chat.id != GROUP_ID):
        await callback.answer()
        return

    user_id = callback.from_user.id
    if not await is_user_subscribed(bot, user_id):
        await callback.answer("Siz hali kanalga obuna bo'lmagansiz! Avval obuna bo'ling, keyin tugmani bosing.", show_alert=True)
        return

    try:
        if muted_by_bot(msg.chat.id, user_id):
            await unmute_user(bot, msg.chat.id, user_id)
            logging.info(f"🔓 Пользователь {user_id} размучен после подтверждения подписки")
    except Exception as e:
        logging.error(f"❌ Не удалось размутить пользователя {user_id}: {e}")
        await callback.answer("Xatolik yuz berdi, qaytadan urinib ko'ring")
        return

    if isinstance(msg, Message) and msg.ephemeral_message_id:
        try:
            await bot.delete_ephemeral_message(msg.chat.id, user_id, msg.ephemeral_message_id)
        except Exception as e:
            logging.warning(f"⚠️ Не удалось удалить ephemeral-сообщение: {e}")

    await callback.answer("Obuna tasdiqlandi! Endi guruhda yozishingiz mumkin.")


@router.message(CommandStart(), F.chat.type == "private")
async def on_start(message: Message) -> None:
    channel_step = f"Kanalga obuna bo'ling: {CHANNEL_URL}" if CHANNEL_URL else "Kanalga obuna bo'ling"
    text = (
        f"👋 Salom, {html.escape(message.from_user.first_name or 'foydalanuvchi')}!\n\n"
        f"📺 Bu bot kanal obunasini tekshirish uchun.\n\n"
        f"📋 BOT QANDAY ISHLAYDI:\n\n"
        f"1️⃣ Guruhga qo'shiling\n"
        f"2️⃣ Bot sizning obunangizni tekshiradi\n"
        f"3️⃣ Agar obuna bo'lmasangiz, guruhda yozish vaqtincha cheklanadi\n"
        f"4️⃣ {channel_step}\n"
        f"5️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
        f"6️⃣ Tayyor! Guruhda yozishingiz mumkin\n\n"
        f"💡 Obuna holatingizni tekshirish uchun /check buyrug'ini ishlating"
    )
    await message.answer(text)


@router.message(Command("check"), F.chat.type == "private")
async def on_check(message: Message, bot: Bot) -> None:
    if await is_user_subscribed(bot, message.from_user.id):
        text = (
            f"✅ Yaxshi! Siz allaqachon kanalga obuna bo'lgansiz.\n\n"
            f"🚀 Guruhga xush kelibsiz!"
        )
    else:
        channel_step = f"Linkni bosing: {CHANNEL_URL}" if CHANNEL_URL else "Kanalga obuna bo'ling"
        text = (
            f"❌ Siz hali kanalga obuna emassiz!\n\n"
            f"1️⃣ {channel_step}\n"
            f"2️⃣ \"Obuna bo'lish\" / \"Join\" tugmasini bosing\n"
            f"3️⃣ Guruhga qayting\n"
            f"4️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n\n"
            f"💡 Obuna bo'lgandan so'ng qayta tekshirish uchun /check buyrug'ini ishlating"
        )
    await message.answer(text)


@router.message(Command("id"), F.chat.type.in_({"group", "supergroup"}))
async def on_id(message: Message, bot: Bot) -> None:
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        is_admin = member.status in ("administrator", "creator")
    except Exception:
        is_admin = False
    if not is_admin:
        # Команда не должна быть лазейкой мимо проверки подписки
        await on_group_message(message, bot)
        return
    text = f"chat.id = {message.chat.id}\nchat.type = {message.chat.type}"
    sent = await safe_send(
        bot, message.chat.id, text,
        ephemeral_message_parameters=EphemeralMessageParameters(receiver_user_id=message.from_user.id),
    )
    if not sent:
        await message.reply(text)
        return
    # Ответ видит только админ — убираем и саму команду из общей ленты
    try:
        await message.delete()
    except Exception:
        pass


@router.message()
async def on_group_message(message: Message, bot: Bot) -> None:
    chat = message.chat
    if chat.type not in ("group", "supergroup"):
        return
    if GROUP_ID is not None and chat.id != GROUP_ID:
        return
    if message.is_automatic_forward:
        return

    # При отправке от имени чата в from_user лежит фейковый пользователь
    if message.sender_chat:
        if message.sender_chat.id == chat.id or is_our_channel(message.sender_chat):
            return  # анонимный админ или пост нашего канала
        # Пишет от имени чужого канала: замутить канал нельзя, просто удаляем
        try:
            await message.delete()
        except Exception:
            pass
        return

    user = message.from_user
    if not user or user.is_bot:
        return

    # Уже замучен ботом (успел отправить несколько сообщений) — без повторного уведомления
    if muted_by_bot(chat.id, user.id):
        try:
            await message.delete()
        except Exception:
            pass
        return

    # Админов и владельца не трогаем
    try:
        member = await bot.get_chat_member(chat.id, user.id)
        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass

    if await is_user_subscribed(bot, user.id):
        return

    # Не подписан: удаляем сообщение, мутим на MUTE_SECONDS, показываем подсказку
    try:
        await message.delete()
    except Exception:
        pass
    try:
        await mute_user(bot, chat.id, user.id)
    except Exception as e:
        logging.error(f"❌ Не удалось замутить пользователя {user.id}: {e}")

    text = (
        f"🔴 Guruhda yozish uchun kanalga obuna bo'ling.\n\n"
        f"👤 {mention(user)}\n\n"
        f"Obuna bo'lgach, quyidagi tugmani bosing — kirish ochiladi."
    )
    await send_notice(bot, chat.id, user, text)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if not CHANNEL_URL:
        logging.warning("⚠️ CHANNEL_LINK не задан, а CHANNEL_ID числовой — кнопки со ссылкой на канал не будет")

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    # Отбрасываем ожидающие обновления
    await bot.delete_webhook(drop_pending_updates=True)

    logging.info("🚀 Запускаем бота...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
