import asyncio
import logging
import os
import re
import time
from typing import Optional
from datetime import datetime, timedelta

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
    logging.info(f"⏰ Сообщение {message_id} запланировано для удаления через {delay_seconds} секунд")
    try:
        await asyncio.sleep(delay_seconds)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logging.info(f"✅ Успешно удалил сообщение {message_id}")
    except Exception as e:
        logging.warning(f"⚠️ Не удалось удалить сообщение {message_id}: {e}")


async def auto_check_subscription(bot: Bot, chat_id: int, user_id: int, user_display_name: str, message_id: int) -> None:
    """Automatically check subscription every 30 seconds and unmute if subscribed"""
    try:
        # Check every 30 seconds for up to 5 minutes (10 checks)
        for check_num in range(10):
            await asyncio.sleep(30)
            
            # Check if user is still in group and muted
            try:
                member = await bot.get_chat_member(chat_id, user_id)
                if not member.is_member or member.status in ["left", "kicked"]:
                    logging.info(f"🔄 Avtomatik tekshirish: foydalanuvchi {user_id} guruhdan chiqib ketdi, tekshirishlarni to'xtataman")
                    return
                    
                # Check if user is still restricted (muted)
                if hasattr(member, 'is_restricted') and not member.is_restricted:
                    logging.info(f"🔄 Avtomatik tekshirish: foydalanuvchi {user_id} allaqachon rozmunlandi, tekshirishlarni to'xtataman")
                    return
                    
            except Exception as e:
                logging.warning(f"⚠️ Avtomatik tekshirish: foydalanuvchi {user_id} holatini tekshirishda xatolik yuz berdi: {e}")
                continue
            
            # Check subscription
            logging.info(f"🔄 Avtomatik tekshirish #{check_num + 1}: foydalanuvchi {user_id} obunasini tekshiraman")
            is_sub = await is_user_subscribed(bot, user_id)
            
            if is_sub:
                logging.info(f"✅ Avtomatik tekshirish: foydalanuvchi {user_id} obuna bo'ldi, rozmunlayman")
                
                try:
                    # Unmute user
                    await unmute_user(bot, chat_id, user_id)
                    logging.info(f"✅ Avtomatik tekshirish: foydalanuvchi {user_id} muvaffaqiyatli rozmunlandi")
                    
                    # Send welcome message
                    welcome_text = f"🎉 Avtomatik ravishda obuna topildi!\n\n👤 {user_display_name}, guruhga xush kelibsiz!\n✅ Endi xabar yozishingiz mumkin."
                    
                    sent_welcome = await bot.send_message(
                        chat_id=chat_id,
                        text=welcome_text,
                        reply_to_message_id=message_id
                    )
                    
                    logging.info(f"📝 Автопроверка: отправил приветствие пользователю {user_id}, message_id={sent_welcome.message_id}")
                    
                    # Auto-delete welcome message after 10 seconds
                    asyncio.create_task(delete_message_after(bot, chat_id, sent_welcome.message_id, 10))
                    
                    # Auto-delete original subscription message after 10 seconds
                    asyncio.create_task(delete_message_after(bot, chat_id, message_id, 10))
                    
                except Exception as e:
                    logging.error(f"❌ Avtomatik tekshirish: foydalanuvchi {user_id} rozmunlanib bo'lmadi: {e}")
                
                return
            else:
                logging.info(f"❌ Avtomatik tekshirish #{check_num + 1}: foydalanuvchi {user_id} hali obuna bo'lmagan")
        
        logging.info(f"⏰ Avtomatik tekshirish: foydalanuvchi {user_id} (5 minut o'tib ketdi) tugadi")
        
    except Exception as e:
        logging.error(f"❌ Avtomatik obuna tekshirishida foydalanuvchi {user_id} xatoligi: {e}")


async def send_delayed_reminder(bot: Bot, chat_id: int, user_id: int, user_display_name: str, message_id: int, delay_seconds: int) -> None:
    """Send reminder after specified delay"""
    try:
        await asyncio.sleep(delay_seconds)
        
        # Check if user is still muted before sending reminder
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if not member.is_member or member.status in ["left", "kicked"]:
                logging.info(f"⏰ Foydalanuvchi {user_id} guruhdan chiqib ketdi, eskirmasini o'tkazaman")
                return
                
            # Check if user is still restricted (muted)
            if hasattr(member, 'is_restricted') and not member.is_restricted:
                logging.info(f"⏰ Foydalanuvchi {user_id} allaqachon rozmunlandi, eskirmasini o'tkazaman")
                return
                
        except Exception as e:
            logging.warning(f"⚠️ Foydalanuvchi {user_id} uchun eskirmasini tekshirishda xatolik yuz berdi: {e}")
            return
        
        await send_reminder(bot, chat_id, user_id, user_display_name, message_id)
        
    except Exception as e:
        logging.error(f"❌ Foydalanuvchi {user_id} uchun eskirmasini jadvalga qo'shishda xatolik yuz berdi: {e}")


async def send_reminder(bot: Bot, chat_id: int, user_id: int, user_display_name: str, message_id: int) -> None:
    """Send reminder message to muted user"""
    try:
        reminder_text = (
            f"⏰ ESDA QOLING!\n\n"
            f"👤 {user_display_name}, siz hali ham ovozsiz!\n\n"
            f"📺 Kanalga obuna bo'lishni va \"✅ Men obuna bo'ldim\" tugmasini bosishni unutmang\n\n"
            f"🔗 Tugma yuqoridagi xabarda ⬆️"
        )
        
        sent_reminder = await bot.send_message(
            chat_id=chat_id,
            text=reminder_text,
            reply_to_message_id=message_id
        )
        
        logging.info(f"⏰ Foydalanuvchi {user_id} uchun eskirmasini yubording, message_id={sent_reminder.message_id}")
        
        # Auto-delete reminder after 30 seconds
        asyncio.create_task(delete_message_after(bot, chat_id, sent_reminder.message_id, 30))
        
    except Exception as e:
        logging.error(f"❌ Foydalanuvchi {user_id} uchun eskirmasini yuborib bo'lmadi: {e}")


def subscribed_keyboard(target_user_id: int = None) -> InlineKeyboardBuilder:
    """Create inline keyboard with subscription button and channel link"""
    kb = InlineKeyboardBuilder()
    
    # Channel link button
    if CHANNEL_LINK:
        kb.button(text="📺 Перейти на канал", url=CHANNEL_LINK)
    elif isinstance(CHANNEL_ID, str) and CHANNEL_ID.startswith('@'):
        kb.button(text="📺 Перейти на канал", url=f"https://t.me/{CHANNEL_ID[1:]}")
    else:
        kb.button(text="📺 Перейти на канал", url=f"https://t.me/c/{str(CHANNEL_ID)[4:]}/1")
    
    # Subscription confirmation button
    if target_user_id:
        # Include target user ID in callback data
        kb.button(text="✅ Я подписался", callback_data=f"i_subscribed_{target_user_id}")
    else:
        # Fallback for backward compatibility
        kb.button(text="✅ Я подписался", callback_data="i_subscribed")
    
    kb.adjust(1)  # One button per row
    return kb


async def handle_new_member(bot: Bot, chat_id: int, user_id: int, message: Message, user_info: dict = None) -> None:
    """Common logic for handling new members"""
    logging.info(f"🔍 Yangi foydalanuvchi aniqlandi: user_id={user_id} chat_id={chat_id}")
    
    # Skip if this is the bot itself
    if user_id == bot.id:
        logging.info(f"🤖 Botni o'zini o'tkazaman: user_id={user_id}")
        return
        
    # Check subscription
    logging.info(f"📋 Foydalanuvchi {user_id} uchun obunani tekshiraman kanal {CHANNEL_ID}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Foydalanuvchi {user_id} uchun obuna holati: {'✅ OBUNA' if is_sub else '❌ OBUNA EMAS'}")
    
    if is_sub:
        logging.info(f"✅ Foydalanuvchi {user_id} allaqachon obuna bo'lgan, ruxsat beraman")
        return

    # Check if user is chat owner (can't be restricted)
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        member_status = getattr(member, "status", "member")
        logging.info(f"👑 Foydalanuvchi {user_id} guruhdagi holati: {member_status}")
        
        if member_status == "creator":
            # Chat owner - skip muting
            logging.info(f"👑 Guruh egasi {user_id} - muxtalif qilish mumkin emas")
            return
    except Exception as e:
        logging.warning(f"⚠️ Foydalanuvchi {user_id} uchun foydalanuvchi holatini olishda xatolik yuz berdi: {e}")

    # Mute user and send instruction
    logging.info(f"🔇 Foydalanuvchi {user_id} obuna emasligi uchun muxtalif qilaman")
    try:
        await mute_user(bot, chat_id, user_id)
        logging.info(f"✅ Foydalanuvchi {user_id} muxtalif qildim")
    except Exception as e:
        logging.error(f"❌ Foydalanuvchi {user_id} muxtalif qilib bo'lmadi: {e}")

    # Get user display name
    user_display_name = "Foydalanuvchi"  # fallback
    if user_info:
        if user_info.get('username'):
            user_display_name = f"@{user_info['username']}"
        elif user_info.get('first_name'):
            user_display_name = user_info['first_name']
            if user_info.get('last_name'):
                user_display_name += f" {user_info['last_name']}"
    
    channel_hint = CHANNEL_LINK or (str(CHANNEL_ID) if isinstance(CHANNEL_ID, str) else "kanal")
    text = (
        f"🔴 DIQQAT! Sizni ovozsiz qildik!\n\n"
        f"👤 <a href=\"tg://user?id={user_id}\">{user_display_name}</a>, guruhda xabar yuborolmaysiz\n\n"
        f"📋 QADAMMA-QADAM KO'RSATMALAR:\n\n"
        f"1️⃣ Kanalga havola orqali o'ting\n"
        f"2️⃣ \"Obuna bo'lish\" / \"Join\" tugmasini bosing\n"
        f"3️⃣ Guruhga qayting\n"
        f"4️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
        f"5️⃣ Tayyor! Endi xabar yozishingiz mumkin\n\n"
        f"💡 Obuna bo'lgandan so'ng quyidagi tugmani bosing:"
    )
    try:
        sent_msg = await message.reply(
            text,
            reply_markup=subscribed_keyboard(user_id).as_markup(),
            disable_web_page_preview=True,
        )
        logging.info(f"📝 Foydalanuvchi {user_id} uchun obuna tugmasi bilan xabarni yubording, message_id={sent_msg.message_id}")
        
        # Schedule reminders
        logging.info(f"⏰ Foydalanuvchi {user_id} uchun eskirmalarini jadvalga qo'shaman ({user_display_name})")
        
        # First reminder after 2 minutes
        asyncio.create_task(send_delayed_reminder(bot, chat_id, user_id, user_display_name, sent_msg.message_id, 120))
        
        # Second reminder after 5 minutes
        asyncio.create_task(send_delayed_reminder(bot, chat_id, user_id, user_display_name, sent_msg.message_id, 300))
        
        # Third reminder after 10 minutes
        asyncio.create_task(send_delayed_reminder(bot, chat_id, user_id, user_display_name, sent_msg.message_id, 600))
        
        # Start automatic subscription checking every 30 seconds
        asyncio.create_task(auto_check_subscription(bot, chat_id, user_id, user_display_name, sent_msg.message_id))
        
    except Exception as e:
        logging.error(f"❌ Foydalanuvchi {user_id} uchun xabarni obuna tugmasi bilan yuborib bo'lmadi: {e}")


async def daily_check_all_members(bot: Bot) -> None:
    """Daily check all group members for subscription status"""
    if not GROUP_ID:
        logging.info("⚠️ GROUP_ID not set, skipping daily check")
        return
    
    try:
        logging.info(f"🔄 Starting daily subscription check for group {GROUP_ID}")
        
        # Get all chat members
        chat_members = []
        async for member in bot.get_chat_members(GROUP_ID):
            chat_members.append(member)
        
        logging.info(f"📋 Found {len(chat_members)} members in group {GROUP_ID}")
        
        checked_count = 0
        muted_count = 0
        already_muted_count = 0
        
        for member in chat_members:
            user_id = member.user.id
            
            # Skip bot itself
            if user_id == bot.id:
                continue
                
            # Skip chat owner (creator)
            if member.status == "creator":
                logging.info(f"👑 Skipping group owner {user_id}")
                continue
                
            # Skip admins (optional - you can remove this if you want to check admins too)
            if member.status == "administrator":
                logging.info(f"👑 Skipping admin {user_id}")
                continue
            
            checked_count += 1
            logging.info(f"🔍 Checking subscription for member {user_id} ({member.user.first_name or 'Unknown'})")
            
            # Check subscription
            is_sub = await is_user_subscribed(bot, user_id)
            
            if not is_sub:
                # Check if user is already muted
                if hasattr(member, 'is_restricted') and member.is_restricted:
                    already_muted_count += 1
                    logging.info(f"🔇 User {user_id} is already muted, skipping")
                    continue
                
                # Mute user
                try:
                    await mute_user(bot, GROUP_ID, user_id)
                    muted_count += 1
                    
                    # Get user display name
                    user_display_name = "Foydalanuvchi"
                    if member.user.username:
                        user_display_name = f"@{member.user.username}"
                    elif member.user.first_name:
                        user_display_name = member.user.first_name
                        if member.user.last_name:
                            user_display_name += f" {member.user.last_name}"
                    
                    # Send notification message
                    notification_text = (
                        f"🔴 DIQQAT! Sizni ovozsiz qildik!\n\n"
                        f"👤 {user_display_name}, siz kanalga obuna emassiz!\n\n"
                        f"📋 QADAMMA-QADAM KO'RSATMALAR:\n\n"
                        f"1️⃣ Kanalga havola orqali o'ting\n"
                        f"2️⃣ \"Obuna bo'lish\" / \"Join\" tugmasini bosing\n"
                        f"3️⃣ Guruhga qayting\n"
                        f"4️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
                        f"5️⃣ Tayyor! Endi xabar yozishingiz mumkin\n\n"
                        f"💡 Obuna bo'lgandan so'ng quyidagi tugmani bosing:"
                    )
                    
                    # Create keyboard with user ID
                    keyboard = subscribed_keyboard(user_id)
                    
                    # Send message
                    sent_msg = await bot.send_message(
                        chat_id=GROUP_ID,
                        text=notification_text,
                        reply_markup=keyboard.as_markup(),
                        disable_web_page_preview=True,
                    )
                    
                    logging.info(f"📝 Sent daily check notification to user {user_id} ({user_display_name}), message_id={sent_msg.message_id}")
                    
                    # Schedule reminders and auto-check
                    asyncio.create_task(send_delayed_reminder(bot, GROUP_ID, user_id, user_display_name, sent_msg.message_id, 120))
                    asyncio.create_task(send_delayed_reminder(bot, GROUP_ID, user_id, user_display_name, sent_msg.message_id, 300))
                    asyncio.create_task(send_delayed_reminder(bot, GROUP_ID, user_id, user_display_name, sent_msg.message_id, 600))
                    asyncio.create_task(auto_check_subscription(bot, GROUP_ID, user_id, user_display_name, sent_msg.message_id))
                    
                except Exception as e:
                    logging.error(f"❌ Failed to mute user {user_id} during daily check: {e}")
            else:
                logging.info(f"✅ User {user_id} is subscribed, no action needed")
        
        logging.info(f"✅ Daily check completed: {checked_count} members checked, {muted_count} newly muted, {already_muted_count} already muted")
        
    except Exception as e:
        logging.error(f"❌ Error during daily member check: {e}")


async def start_daily_checker(bot: Bot) -> None:
    """Start the daily checker task"""
    while True:
        try:
            # Wait until next day at 9:00 AM
            now = datetime.now()
            next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            
            wait_seconds = (next_run - now).total_seconds()
            logging.info(f"⏰ Next daily check scheduled for {next_run.strftime('%Y-%m-%d %H:%M:%S')} (in {wait_seconds:.0f} seconds)")
            
            await asyncio.sleep(wait_seconds)
            
            # Run daily check
            await daily_check_all_members(bot)
            
        except Exception as e:
            logging.error(f"❌ Error in daily checker task: {e}")
            await asyncio.sleep(3600)  # Wait 1 hour before retrying


@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message, bot: Bot) -> None:
    """Handle new members joining via invite links"""
    logging.info(f"👥 Yangi foydalanuvchilar guruhdagi chat_id={message.chat.id} holatini aniqladi")
    
    if GROUP_ID is not None and message.chat.id != GROUP_ID:
        logging.info(f"⚠️ Chat {message.chat.id} o'tkazaman - guruhdan farq qiluvchi {GROUP_ID}")
        return

    if not message.new_chat_members:
        logging.info("⚠️ Chatda yangi foydalanuvchilar topilmadi")
        return

    logging.info(f"📋 {len(message.new_chat_members)} yangi foydalanuvchilarni qayta ishlayman")
    for user in message.new_chat_members:
        logging.info(f"👤 Yangi foydalanuvchini qayta ishlayman: {user.first_name} (@{user.username}) user_id={user.id}")
        user_info = {
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name
        }
        await handle_new_member(bot, message.chat.id, user.id, message, user_info)


@router.chat_join_request()
async def on_chat_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    """Handle join requests (when group requires approval)"""
    logging.info(f"📝 Kirish so'ralishi user_id={event.from_user.id} chat_id={event.chat.id} holatini aniqladi")
    
    if GROUP_ID is not None and event.chat.id != GROUP_ID:
        logging.info(f"⚠️ Chat {event.chat.id} o'tkazaman - guruhdan farq qiluvchi {GROUP_ID}")
        return

    user_id = event.from_user.id
    logging.info(f"📋 Foydalanuvchi {user_id} uchun obunani tekshiraman")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Foydalanuvchi {user_id} uchun obuna holati: {'✅ OBUNA' if is_sub else '❌ OBUNA EMAS'}")
    
    if is_sub:
        # Approve the request
        logging.info(f"✅ Kirish so'ralishi {user_id} uchun qabul qilindi")
        await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=user_id)
    else:
        # Decline the request
        logging.info(f"❌ Kirish so'ralishi {user_id} uchun rad etildi")
        await bot.decline_chat_join_request(chat_id=event.chat.id, user_id=user_id)
        
        # Try to notify user in DM
        user_display_name = "Foydalanuvchi"  # fallback
        if event.from_user.username:
            user_display_name = f"@{event.from_user.username}"
        elif event.from_user.first_name:
            user_display_name = event.from_user.first_name
            if event.from_user.last_name:
                user_display_name += f" {event.from_user.last_name}"
        
        if CHANNEL_LINK:
            text = (
                f"🔴 VARNING! Sizning kirish so'ralishi rad etildi!\n\n"
                f"👤 {user_display_name}, guruhdaga kirish uchun:\n\n"
                f"📋 QO'LLAB-QO'LLAB TAYYORLASH:\n\n"
                f"1️⃣ Linkni bosing: {CHANNEL_LINK}\n"
                f"2️⃣ \"Obuna bo'lish\" / \"Join\" tugmasini bosing\n"
                f"3️⃣ Guruhga qayting\n"
                f"4️⃣ Yangi so'ralishni yuboring\n"
                f"5️⃣ Tugatildi! Avtomatik kirishga ruxsat beriladi\n\n"
                f"💡 Obuna bo'lgandan so'ng so'ralish avtomatik ravishda qabul qilinadi!"
            )
        else:
            text = (
                f"🔴 VARNING! Sizning kirish so'ralishi rad etildi!\n\n"
                f"👤 {user_display_name}, guruhdaga kirish uchun:\n\n"
                f"📋 QO'LLAB-QO'LLAB TAYYORLASH:\n\n"
                f"1️⃣ Obligatsion kanalga obuna bo'ling\n"
                f"2️⃣ Guruhga qayting\n"
                f"3️⃣ Yangi so'ralishni yuboring\n"
                f"4️⃣ Tugatildi! Avtomatik kirishga ruxsat beriladi\n\n"
                f"💡 Obuna bo'lgandan so'ng so'ralish avtomatik ravishda qabul qilinadi!"
            )
        try:
            await bot.send_message(user_id, text)
            logging.info(f"📱 Foydalanuvchi {user_id} uchun xabarni DMga yubording")
        except Exception as e:
            logging.warning(f"⚠️ Foydalanuvchi {user_id} uchun DMga xabarni yuborib bo'lmadi: {e}")


@router.callback_query(F.data.startswith("i_subscribed"))
async def on_subscribed_click(callback: CallbackQuery, bot: Bot) -> None:
    logging.info(f"🔘 Tugma 'Obuna bo'ldim' foydalanuvchi user_id={callback.from_user.id} chat_id={callback.message.chat.id if callback.message else 'nomalum'} holatini aniqladi")
    
    chat = callback.message.chat if callback.message else None
    if chat is None:
        logging.warning("⚠️ Chat haqida ma'lumot yo'q kollabekda")
        await callback.answer()
        return

    if GROUP_ID is not None and chat.id != GROUP_ID:
        logging.info(f"⚠️ Tugma guruhdagi {chat.id} ga boshlandi, {GROUP_ID} kutildi")
        await callback.answer()
        return

    user_id = callback.from_user.id
    logging.info(f"🔍 Tugmani bosishni qayta ishlayman foydalanuvchi user_id={user_id}")
    
    # Extract target user ID from callback data
    callback_data = callback.data
    if callback_data == "i_subscribed":
        # Fallback for old format - try to get from reply_to_message
        if callback.message and callback.message.reply_to_message:
            mention_pattern = r'tg://user\?id=(\d+)'
            reply_text = callback.message.reply_to_message.text
            if reply_text:
                match = re.search(mention_pattern, reply_text)
                if match:
                    mentioned_user_id = int(match.group(1))
                    logging.info(f"📝 Eski formatni qo'llab-quvvatlash: tugma {mentioned_user_id} uchun mo'ljallangan edi")
                else:
                    logging.warning(f"⚠️ Foydalanuvchi uchun tugma matni bo'ylab foydalanuvchi topilmadi: {user_id}")
                    await callback.answer("Xatolik: tugma uchun kimligini aniqlab bo'lmadi", show_alert=True)
                    return
            else:
                logging.warning(f"⚠️ reply_to_message.text {user_id} uchun None")
                await callback.answer("Xatolik: tugma uchun kimligini aniqlab bo'lmadi", show_alert=True)
                return
        else:
            logging.warning(f"⚠️ Eski format uchun tugma uchun reply_to_message yo'q")
            await callback.answer("Xatolik: tugma uchun kimligini aniqlab bo'lmadi", show_alert=True)
            return
    else:
        # New format: i_subscribed_123456
        try:
            mentioned_user_id = int(callback_data.split("_")[-1])
            logging.info(f"📝 Yangi format: tugma {mentioned_user_id} uchun mo'ljallangan edi")
        except (ValueError, IndexError):
            logging.error(f"❌ Noto'g'ri kallback_data formati: {callback_data}")
            await callback.answer("Xatolik: noto'g'ri tugma formati", show_alert=True)
            return
    
    # Check if this user is the one who was mentioned in the button
    logging.info(f"📝 Tugma {mentioned_user_id} uchun mo'ljallangan edi, foydalanuvchi {user_id} bosdi")
    if user_id != mentioned_user_id:
        logging.warning(f"🚫 Noto'g'ri foydalanuvchi {user_id} tugmani bosdi, {mentioned_user_id} uchun mo'ljallangan edi")
        await callback.answer("Bu tugma siz uchun emas!", show_alert=True)
        return
    logging.info(f"✅ To'g'ri foydalanuvchi {user_id} o'z tugmasini bosdi")
    
    # Now check subscription of the mentioned user (who should be unmuted)
    logging.info(f"📋 Foydalanuvchi {mentioned_user_id} uchun obunani tekshiraman")
    is_sub = await is_user_subscribed(bot, mentioned_user_id)
    logging.info(f"📊 Foydalanuvchi {mentioned_user_id} uchun obuna holati: {'✅ OBUNA' if is_sub else '❌ OBUNA EMAS'}")
    
    if is_sub:
        try:
            # Check if mentioned user is chat owner (can't be restricted)
            member = await bot.get_chat_member(chat.id, mentioned_user_id)
            member_status = getattr(member, "status", "member")
            logging.info(f"👑 Foydalanuvchi {mentioned_user_id} guruhdagi holati: {member_status}")
            
            if member_status == "creator":
                # Chat owner - just send welcome message without unmuting
                logging.info(f"👑 Guruh egasi {mentioned_user_id} obuna tasdiqladi")
                await callback.answer("Obuna tasdiqlandi")
                return
            
            logging.info(f"🔓 Foydalanuvchi {mentioned_user_id} obuna tasdiqlangandan so'ng rozmunlayman")
            await unmute_user(bot, chat.id, mentioned_user_id)
            logging.info(f"✅ Foydalanuvchi {mentioned_user_id} muxtalif qildim")
        except Exception as e:
            logging.error(f"❌ Foydalanuvchi {mentioned_user_id} muxtalif qilib bo'lmadi: {e}")
        
        # Reply to the original join message if available
        try:
            if callback.message and callback.message.reply_to_message:
                sent = await bot.send_message(
                    chat_id=chat.id,
                    text="🎉 Guruhga xush kelibsiz!\n\n✅ Endi xabar yozishingiz mumkin.",
                    reply_to_message_id=callback.message.reply_to_message.message_id,
                )
                logging.info(f"📝 Foydalanuvchi {mentioned_user_id} uchun xush kelish xabarni yubording, message_id={sent.message_id}")
            else:
                sent = await callback.message.answer("🎉 Guruhga xush kelibsiz!\n\n✅ Endi xabar yozishingiz mumkin.")
                logging.info(f"📝 Foydalanuvchi {mentioned_user_id} uchun xush kelish xabarni yubording, message_id={sent.message_id}")
            
            # Schedule deletion of the greeting too
            logging.info(f"⏰ Xush kelish xabarni {sent.message_id} 10 sekund ichida o'chirishni jadvalga qo'shaman")
            asyncio.create_task(delete_message_after(bot, chat.id, sent.message_id, 10))
        except Exception as e:
            logging.error(f"❌ Foydalanuvchi {mentioned_user_id} uchun xush kelish xabarni yuborib bo'lmadi: {e}")
        
        # Schedule deletion of the subscribe prompt message (with the button)
        try:
            logging.info(f"⏰ Tugma bilan xabarni {callback.message.message_id} 10 sekund ichida o'chirishni jadvalga qo'shaman")
            asyncio.create_task(delete_message_after(bot, chat.id, callback.message.message_id, 10))
        except Exception as e:
            logging.error(f"❌ Tugma bilan xabarni jadvalga qo'shishda xatolik yuz berdi: {e}")
        
        await callback.answer("Obuna tasdiqlandi")
        logging.info(f"✅ Obuna tasdiqlandi foydalanuvchi {mentioned_user_id} uchun")
    else:
        logging.warning(f"⚠️ Tugma bilan foydalanuvchi {mentioned_user_id} obuna emas")
        await callback.answer("Foydalanuvchi hali obuna emas", show_alert=False)


@router.message(CommandStart())
async def on_start(message: Message, bot: Bot) -> None:
    """Handle /start command"""
    logging.info(f"🚀 /start buyrug'i foydalanuvchi user_id={message.from_user.id} holatini aniqladi")
    
    if CHANNEL_LINK:
        text = (
            f"👋 Salom, {message.from_user.first_name or 'foydalanuvchi'}!\n\n"
            f"📺 Bu bot kanal obuna tekshirish uchun.\n\n"
            f"📋 BOT QANDAY ISHLAYDI:\n\n"
            f"1️⃣ Guruhga qo'shiling\n"
            f"2️⃣ Bot sizning obunangizni tekshiradi\n"
            f"3️⃣ Agar obuna emas bo'lsangiz, muxtalif qilinasiz\n"
            f"4️⃣ Kanalga obuna bo'ling: {CHANNEL_LINK}\n"
            f"5️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
            f"6️⃣ Tugatildi! Guruhda yozishingiz mumkin\n\n"
            f"💡 /check buyrug'i bilan obuna holatingizni tekshirishni ishlating"
        )
    else:
        text = (
            f"👋 Salom, {message.from_user.first_name or 'foydalanuvchi'}!\n\n"
            f"📺 Bu bot obligatsion kanal uchun.\n\n"
            f"📋 BOT QANDAY ISHLAYDI:\n\n"
            f"1️⃣ Guruhga qo'shiling\n"
            f"2️⃣ Bot sizning obunangizni tekshiradi\n"
            f"3️⃣ Agar obuna emas bo'lsangiz, muxtalif qilinasiz\n"
            f"4️⃣ Obligatsion kanalga obuna bo'ling\n"
            f"5️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
            f"6️⃣ Tugatildi! Guruhda yozishingiz mumkin\n\n"
            f"💡 /check buyrug'i bilan obuna holatingizni tekshirishni ishlating"
        )
    
    await message.answer(text)
    logging.info(f"📝 Foydalanuvchi {message.from_user.id} uchun xush kelish xabarni yubording")


@router.message(Command("check"))
async def on_check(message: Message, bot: Bot) -> None:
    """Handle /check command"""
    logging.info(f"🔍 /check buyrug'i foydalanuvchi user_id={message.from_user.id} holatini aniqladi")
    
    if message.chat.type != "private":
        logging.info(f"⚠️ /check buyrug'i shaxsiy chatda boshlandi, o'tkazaman")
        return
    
    user_id = message.from_user.id
    logging.info(f"📋 Foydalanuvchi {user_id} uchun obunani /check buyrug'i uchun tekshiraman")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Foydalanuvchi {user_id} uchun obuna holati: {'✅ OBUNA' if is_sub else '❌ OBUNA EMAS'}")
    
    if is_sub:
        text = (
            f"✅ Yaxshi! Siz allaqachon kanalga obuna bo'lgansiz.\n\n"
            f"🎯 Endi sizning qilishingiz mumkin:\n"
            f"• Guruhga qo'shiling\n"
            f"• Xabar yozishda cheklovsizlik\n"
            f"• Barcha funksiyalarga kirish\n\n"
            f"🚀 Guruhga xush kelibsiz!"
        )
    else:
        if CHANNEL_LINK:
            text = (
                f"❌ Siz hali kanalga obuna emassiz!\n\n"
                f"📋 NIMA QILISHI:\n\n"
                f"1️⃣ Linkni bosing: {CHANNEL_LINK}\n"
                f"2️⃣ \"Obuna bo'lish\" / \"Join\" tugmasini bosing\n"
                f"3️⃣ Guruhga qayting\n"
                f"4️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
                f"5️⃣ Tugatildi! Endi siz yozishingiz mumkin\n\n"
                f"💡 Obuna bo'lgandan so'ng /check buyrug'ini qayta ishlashingiz mumkin"
            )
        else:
            text = (
                f"❌ Siz hali obligatsion kanalga obuna emassiz!\n\n"
                f"📋 NIMA QILISHI:\n\n"
                f"1️⃣ Obligatsion kanalga obuna bo'ling\n"
                f"2️⃣ Guruhga qayting\n"
                f"3️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
                f"4️⃣ Tugatildi! Endi siz yozishingiz mumkin\n\n"
                f"💡 Obuna bo'lgandan so'ng /check buyrug'ini qayta ishlashingiz mumkin"
            )
    
    await message.answer(text)
    logging.info(f"📝 Foydalanuvchi {user_id} uchun obuna holati natijasini yubording")


@router.message(Command("id"))
async def on_id(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    chat = message.chat
    logging.info(f"🆔 /id buyrug'i foydalanuvchi user_id={user_id} chat_id={chat.id}, chat_type={chat.type} holatini aniqladi")
    
    # Only respond in groups/supergroups
    if chat.type not in ("group", "supergroup"):
        logging.info(f"⚠️ /id buyrug'i noto'g'ri chat turida ishlatilgan: {chat.type}")
        await message.answer("Bu buyruq faqat guruhdada ishlaydi.")
        return

    # Additionally, require that the user be an admin/creator (to not spam)
    try:
        member = await bot.get_chat_member(chat.id, user_id)
        member_status = getattr(member, "status", "member")
        logging.info(f"👑 Foydalanuvchi {user_id} guruhdagi holati: {member_status}")
        
        if member_status not in ("administrator", "creator"):
            logging.warning(f"🚫 Noto'g'ri foydalanuvchi {user_id} /id buyrug'ini ishlatmoqchi edi")
            await message.answer("Bu buyruq faqat guruhdagi administratorlarga murojaat qilishi mumkin.")
            return
    except Exception as e:
        logging.warning(f"⚠️ Foydalanuvchi {user_id} uchun /id buyrug'i uchun foydalanuvchi holatini tekshirishda xatolik yuz berdi: {e}")

    await message.answer(f"chat.id = {chat.id}\nchat.type = {chat.type}")
    logging.info(f"✅ Chat ID ma'lumotini administrator {user_id} uchun yubording: chat.id={chat.id}, chat.type={chat.type}")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    # Drop pending updates
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Start the bot
    logging.info("🚀 Starting bot...")
    
    # Start daily checker task
    asyncio.create_task(start_daily_checker(bot))
    logging.info("⏰ Daily checker task started")
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())