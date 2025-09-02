import asyncio
import logging
import os
import re
import time
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, ChatPermissions, ChatJoinRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

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


router = Router()


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        status = getattr(member, "status", None)
        return status in ("member", "administrator", "creator")
    except Exception as e:
        logging.warning("get_chat_member failed for user %s: %s", user_id, e)
        return False


async def mute_user(bot: Bot, chat_id: int, user_id: int) -> None:
    permissions = ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
    )
    await bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=permissions)


async def unmute_user(bot: Bot, chat_id: int, user_id: int) -> None:
    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
    )
    await bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=permissions)


async def delete_message_after(bot: Bot, chat_id: int, message_id: int, delay_seconds: int) -> None:
    try:
        await asyncio.sleep(delay_seconds)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def subscribed_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Obuna bo'ldim", callback_data="i_subscribed")
    kb.adjust(1)
    return kb


async def handle_new_member(bot: Bot, chat_id: int, user_id: int, message: Message) -> None:
    """Common logic for handling new members"""
    # Skip if this is the bot itself
    if user_id == bot.id:
        return
        
    # Check subscription
    is_sub = await is_user_subscribed(bot, user_id)
    if is_sub:
        return

    # Check if user is chat owner (can't be restricted)
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if getattr(member, "status", "member") == "creator":
            # Chat owner - skip muting
            return
    except Exception:
        pass

    # Mute user and send instruction
    try:
        await mute_user(bot, chat_id, user_id)
    except Exception as e:
        logging.warning("Failed to mute user %s: %s", user_id, e)

    channel_hint = CHANNEL_LINK or (str(CHANNEL_ID) if isinstance(CHANNEL_ID, str) else "kanal")
    text = (
        f"<a href=\"tg://user?id={user_id}\">Foydalanuvchi</a>, bu guruhda xabar yuborish uchun avval kanalga obuna bo'ling.\n"
        f"Havola: {channel_hint}\nObuna bo'lgach, quyidagi tugmani bosing."
    )
    try:
        await message.reply(
            text,
            reply_markup=subscribed_keyboard().as_markup(),
            disable_web_page_preview=True,
        )
    except Exception:
        pass


@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message, bot: Bot) -> None:
    """Handle new members joining via invite links"""
    if GROUP_ID is not None and message.chat.id != GROUP_ID:
        return

    if not message.new_chat_members:
        return

    for user in message.new_chat_members:
        await handle_new_member(bot, message.chat.id, user.id, message)


@router.chat_join_request()
async def on_chat_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    """Handle join requests (when group requires approval)"""
    if GROUP_ID is not None and event.chat.id != GROUP_ID:
        return

    user_id = event.from_user.id
    is_sub = await is_user_subscribed(bot, user_id)
    
    if is_sub:
        # Approve the request
        await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=user_id)
    else:
        # Decline the request
        await bot.decline_chat_join_request(chat_id=event.chat.id, user_id=user_id)
        
        # Try to notify user in DM
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


@router.callback_query(F.data == "i_subscribed")
async def on_subscribed_click(callback: CallbackQuery, bot: Bot) -> None:
    chat = callback.message.chat if callback.message else None
    if chat is None:
        await callback.answer()
        return

    if GROUP_ID is not None and chat.id != GROUP_ID:
        await callback.answer()
        return

    user_id = callback.from_user.id
    
    # Check if this user is the one who was mentioned in the original message
    if callback.message and callback.message.reply_to_message:
        # Extract user ID from the mention in the original message
        mention_pattern = r'tg://user\?id=(\d+)'
        match = re.search(mention_pattern, callback.message.reply_to_message.text)
        if match:
            mentioned_user_id = int(match.group(1))
            if user_id != mentioned_user_id:
                await callback.answer("Bu tugma siz uchun emas!", show_alert=True)
                return
    else:
        # If no reply_to_message, check if this user was recently muted
        # This is a fallback for cases where the message structure might be different
        pass

    is_sub = await is_user_subscribed(bot, user_id)
    if is_sub:
        try:
            # Check if user is chat owner (can't be restricted)
            member = await bot.get_chat_member(chat.id, user_id)
            if getattr(member, "status", "member") == "creator":
                # Chat owner - just send welcome message without unmuting
                await callback.answer("Obuna tasdiqlandi")
                return
            
            await unmute_user(bot, chat.id, user_id)
        except Exception as e:
            logging.warning("Failed to unmute user %s: %s", user_id, e)
        # Reply to the original join message if available
        try:
            if callback.message and callback.message.reply_to_message:
                sent = await bot.send_message(
                    chat_id=chat.id,
                    text="Kirish ochildi. Xush kelibsiz!",
                    reply_to_message_id=callback.message.reply_to_message.message_id,
                )
            else:
                sent = await callback.message.answer("Kirish ochildi. Xush kelibsiz!")
            # Schedule deletion of the greeting too
            asyncio.create_task(delete_message_after(bot, chat.id, sent.message_id, 10))
        except Exception:
            pass
        # Schedule deletion of the subscribe prompt message (with the button)
        try:
            asyncio.create_task(delete_message_after(bot, chat.id, callback.message.message_id, 10))
        except Exception:
            pass
        await callback.answer("Obuna tasdiqlandi")
    else:
        await callback.answer("Siz hali obuna bo'lmaggansiz", show_alert=False)


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    lines = [
        "Привет! Я проверяю подписку на канал перед отправкой сообщений в группе.",
    ]
    if CHANNEL_LINK:
        lines.append(f"Сначала подпишитесь на канал: {CHANNEL_LINK}")
    await message.answer("\n".join(lines))


@router.message(Command("check"))
async def on_check(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    subscribed = await is_user_subscribed(bot, user_id)
    if not subscribed:
        if CHANNEL_LINK:
            await message.answer(
                f"Вы ещё не подписаны. Подпишитесь: {CHANNEL_LINK} и нажмите кнопку в группе."
            )
        else:
            await message.answer("Вы ещё не подписаны на обязательный канал. Подпишитесь и нажмите кнопку в группе.")
        return

    await message.answer("Подписка найдена. Если вы были ограничены в группе — кнопка теперь откроет доступ.")


@router.message(Command("id"))
async def on_id(message: Message, bot: Bot) -> None:
    chat = message.chat
    # Отвечаем только в группах/супергруппах
    if chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в группе.")
        return

    # Дополнительно потребуем, чтобы вызвал админ/создатель (чтоб не спамили)
    try:
        member = await bot.get_chat_member(chat.id, message.from_user.id)
        if getattr(member, "status", "member") not in ("administrator", "creator"):
            await message.answer("Команда доступна только администраторам группы.")
            return
    except Exception:
        pass

    await message.answer(f"chat.id = {chat.id}\nchat.type = {chat.type}")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    # Drop pending updates
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Start bot polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())