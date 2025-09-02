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
    logging.info(f"⏰ Scheduled deletion of message {message_id} in {delay_seconds} seconds")
    try:
        await asyncio.sleep(delay_seconds)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logging.info(f"✅ Successfully deleted message {message_id}")
    except Exception as e:
        logging.warning(f"⚠️ Failed to delete message {message_id}: {e}")


def subscribed_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Obuna bo'ldim", callback_data="i_subscribed")
    kb.adjust(1)
    return kb


async def handle_new_member(bot: Bot, chat_id: int, user_id: int, message: Message) -> None:
    """Common logic for handling new members"""
    logging.info(f"🔍 New member detected: user_id={user_id} in chat_id={chat_id}")
    
    # Skip if this is the bot itself
    if user_id == bot.id:
        logging.info(f"🤖 Skipping bot itself: user_id={user_id}")
        return
        
    # Check subscription
    logging.info(f"📋 Checking subscription for user_id={user_id} in channel={CHANNEL_ID}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Subscription status for user_id={user_id}: {'✅ SUBSCRIBED' if is_sub else '❌ NOT SUBSCRIBED'}")
    
    if is_sub:
        logging.info(f"✅ User {user_id} is already subscribed, allowing access")
        return

    # Check if user is chat owner (can't be restricted)
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        member_status = getattr(member, "status", "member")
        logging.info(f"👑 User {user_id} status in group: {member_status}")
        
        if member_status == "creator":
            # Chat owner - skip muting
            logging.info(f"👑 Skipping chat owner {user_id} - cannot be restricted")
            return
    except Exception as e:
        logging.warning(f"⚠️ Failed to get member status for user {user_id}: {e}")

    # Mute user and send instruction
    logging.info(f"🔇 Muting user {user_id} for not being subscribed")
    try:
        await mute_user(bot, chat_id, user_id)
        logging.info(f"✅ Successfully muted user {user_id}")
    except Exception as e:
        logging.error(f"❌ Failed to mute user {user_id}: {e}")

    channel_hint = CHANNEL_LINK or (str(CHANNEL_ID) if isinstance(CHANNEL_ID, str) else "kanal")
    text = (
        f"<a href=\"tg://user?id={user_id}\">Foydalanuvchi</a>, bu guruhda xabar yuborish uchun avval kanalga obuna bo'ling.\n"
        f"Havola: {channel_hint}\nObuna bo'lgach, quyidagi tugmani bosing."
    )
    try:
        sent_msg = await message.reply(
            text,
            reply_markup=subscribed_keyboard().as_markup(),
            disable_web_page_preview=True,
        )
        logging.info(f"📝 Sent subscription prompt with button to user {user_id}, message_id={sent_msg.message_id}")
    except Exception as e:
        logging.error(f"❌ Failed to send subscription prompt to user {user_id}: {e}")


@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message, bot: Bot) -> None:
    """Handle new members joining via invite links"""
    logging.info(f"👥 New chat members event detected in chat_id={message.chat.id}")
    
    if GROUP_ID is not None and message.chat.id != GROUP_ID:
        logging.info(f"⚠️ Skipping chat {message.chat.id} - not target group {GROUP_ID}")
        return

    if not message.new_chat_members:
        logging.info("⚠️ No new chat members found in message")
        return

    logging.info(f"📋 Processing {len(message.new_chat_members)} new members")
    for user in message.new_chat_members:
        logging.info(f"👤 Processing new member: {user.first_name} (@{user.username}) user_id={user.id}")
        await handle_new_member(bot, message.chat.id, user.id, message)


@router.chat_join_request()
async def on_chat_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    """Handle join requests (when group requires approval)"""
    logging.info(f"📝 Join request from user_id={event.from_user.id} in chat_id={event.chat.id}")
    
    if GROUP_ID is not None and event.chat.id != GROUP_ID:
        logging.info(f"⚠️ Skipping join request in chat {event.chat.id} - not target group {GROUP_ID}")
        return

    user_id = event.from_user.id
    logging.info(f"📋 Checking subscription for join request from user_id={user_id}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Join request subscription status for user_id={user_id}: {'✅ SUBSCRIBED' if is_sub else '❌ NOT SUBSCRIBED'}")
    
    if is_sub:
        # Approve the request
        logging.info(f"✅ Approving join request from subscribed user {user_id}")
        await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=user_id)
    else:
        # Decline the request
        logging.info(f"❌ Declining join request from unsubscribed user {user_id}")
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
            logging.info(f"📱 Sent DM notification to user {user_id}")
        except Exception as e:
            logging.warning(f"⚠️ Failed to send DM to user {user_id}: {e}")


@router.callback_query(F.data == "i_subscribed")
async def on_subscribed_click(callback: CallbackQuery, bot: Bot) -> None:
    logging.info(f"🔘 Button 'Obuna bo'ldim' clicked by user_id={callback.from_user.id} in chat_id={callback.message.chat.id if callback.message else 'unknown'}")
    
    chat = callback.message.chat if callback.message else None
    if chat is None:
        logging.warning("⚠️ No chat info in callback")
        await callback.answer()
        return

    if GROUP_ID is not None and chat.id != GROUP_ID:
        logging.info(f"⚠️ Button clicked in wrong chat {chat.id}, expected {GROUP_ID}")
        await callback.answer()
        return

    user_id = callback.from_user.id
    logging.info(f"🔍 Processing button click from user_id={user_id}")
    
    # Check if this user is the one who was mentioned in the original message
    if callback.message and callback.message.reply_to_message:
        # Extract user ID from the mention in the original message
        mention_pattern = r'tg://user\?id=(\d+)'
        match = re.search(mention_pattern, callback.message.reply_to_message.text)
        if match:
            mentioned_user_id = int(match.group(1))
            logging.info(f"📝 Button was meant for user_id={mentioned_user_id}, clicked by user_id={user_id}")
            if user_id != mentioned_user_id:
                logging.warning(f"🚫 Wrong user {user_id} clicked button meant for {mentioned_user_id}")
                await callback.answer("Bu tugma siz uchun emas!", show_alert=True)
                return
            logging.info(f"✅ Correct user {user_id} clicked their button")
    else:
        logging.info("ℹ️ No reply_to_message, proceeding with subscription check")

    logging.info(f"📋 Checking subscription for button click from user_id={user_id}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Button click subscription status for user_id={user_id}: {'✅ SUBSCRIBED' if is_sub else '❌ NOT SUBSCRIBED'}")
    
    if is_sub:
        try:
            # Check if user is chat owner (can't be restricted)
            member = await bot.get_chat_member(chat.id, user_id)
            member_status = getattr(member, "status", "member")
            logging.info(f"👑 User {user_id} status in group: {member_status}")
            
            if member_status == "creator":
                # Chat owner - just send welcome message without unmuting
                logging.info(f"👑 Chat owner {user_id} confirmed subscription")
                await callback.answer("Obuna tasdiqlandi")
                return
            
            logging.info(f"🔓 Unmuting user {user_id} after subscription confirmation")
            await unmute_user(bot, chat.id, user_id)
            logging.info(f"✅ Successfully unmuted user {user_id}")
        except Exception as e:
            logging.error(f"❌ Failed to unmute user {user_id}: {e}")
        
        # Reply to the original join message if available
        try:
            if callback.message and callback.message.reply_to_message:
                sent = await bot.send_message(
                    chat_id=chat.id,
                    text="Kirish ochildi. Xush kelibsiz!",
                    reply_to_message_id=callback.message.reply_to_message.message_id,
                )
                logging.info(f"📝 Sent welcome message reply to user {user_id}, message_id={sent.message_id}")
            else:
                sent = await callback.message.answer("Kirish ochildi. Xush kelibsiz!")
                logging.info(f"📝 Sent welcome message to user {user_id}, message_id={sent.message_id}")
            
            # Schedule deletion of the greeting too
            logging.info(f"⏰ Scheduling deletion of welcome message {sent.message_id} in 10 seconds")
            asyncio.create_task(delete_message_after(bot, chat.id, sent.message_id, 10))
        except Exception as e:
            logging.error(f"❌ Failed to send welcome message to user {user_id}: {e}")
        
        # Schedule deletion of the subscribe prompt message (with the button)
        try:
            logging.info(f"⏰ Scheduling deletion of button message {callback.message.message_id} in 10 seconds")
            asyncio.create_task(delete_message_after(bot, chat.id, callback.message.message_id, 10))
        except Exception as e:
            logging.error(f"❌ Failed to schedule deletion of button message: {e}")
        
        await callback.answer("Obuna tasdiqlandi")
        logging.info(f"✅ Subscription confirmed for user {user_id}")
    else:
        logging.warning(f"⚠️ User {user_id} clicked button but is not subscribed")
        await callback.answer("Siz hali obuna bo'lmaggansiz", show_alert=False)


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    logging.info(f"🚀 /start command from user_id={message.from_user.id} in chat_id={message.chat.id}")
    lines = [
        "Привет! Я проверяю подписку на канал перед отправкой сообщений в группе.",
    ]
    if CHANNEL_LINK:
        lines.append(f"Сначала подпишитесь на канал: {CHANNEL_LINK}")
    await message.answer("\n".join(lines))
    logging.info(f"✅ Sent start message to user {message.from_user.id}")


@router.message(Command("check"))
async def on_check(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    logging.info(f"🔍 /check command from user_id={user_id} in chat_id={message.chat.id}")
    
    logging.info(f"📋 Checking subscription for /check command from user_id={user_id}")
    subscribed = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 /check subscription status for user_id={user_id}: {'✅ SUBSCRIBED' if subscribed else '❌ NOT SUBSCRIBED'}")
    
    if not subscribed:
        if CHANNEL_LINK:
            await message.answer(
                f"Вы ещё не подписаны. Подпишитесь: {CHANNEL_LINK} и нажмите кнопку в группе."
            )
            logging.info(f"📝 Sent 'not subscribed' message to user {user_id}")
        else:
            await message.answer("Вы ещё не подписаны на обязательный канал. Подпишитесь и нажмите кнопку в группе.")
            logging.info(f"📝 Sent 'not subscribed' message to user {user_id}")
        return

    await message.answer("Подписка найдена. Если вы были ограничены в группе — кнопка теперь откроет доступ.")
    logging.info(f"✅ Sent 'subscribed' confirmation to user {user_id}")


@router.message(Command("id"))
async def on_id(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    chat = message.chat
    logging.info(f"🆔 /id command from user_id={user_id} in chat_id={chat.id}, chat_type={chat.type}")
    
    # Отвечаем только в группах/супергруппах
    if chat.type not in ("group", "supergroup"):
        logging.info(f"⚠️ /id command used in wrong chat type: {chat.type}")
        await message.answer("Эта команда работает только в группе.")
        return

    # Дополнительно потребуем, чтобы вызвал админ/создатель (чтоб не спамили)
    try:
        member = await bot.get_chat_member(chat.id, user_id)
        member_status = getattr(member, "status", "member")
        logging.info(f"👑 User {user_id} status in group: {member_status}")
        
        if member_status not in ("administrator", "creator"):
            logging.warning(f"🚫 Non-admin user {user_id} tried to use /id command")
            await message.answer("Команда доступна только администраторам группы.")
            return
    except Exception as e:
        logging.warning(f"⚠️ Failed to check user status for /id command: {e}")

    await message.answer(f"chat.id = {chat.id}\nchat.type = {chat.type}")
    logging.info(f"✅ Sent chat ID info to admin user {user_id}: chat.id={chat.id}, chat.type={chat.type}")


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