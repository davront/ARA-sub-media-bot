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

# Flood control settings
MESSAGE_DELAY = 0.5  # Delay between messages in seconds
MAX_RETRIES = 3  # Maximum retry attempts for failed messages
RETRY_DELAY = 5  # Delay before retry in seconds


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


async def safe_send_message(bot: Bot, chat_id: int, text: str, **kwargs) -> Optional[Message]:
    """
    Safely send message with flood control and retry logic
    """
    for attempt in range(MAX_RETRIES):
        try:
            # Add delay between messages to avoid flood control
            if attempt > 0:
                await asyncio.sleep(MESSAGE_DELAY)
            
            message = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            logging.info(f"✅ Сообщение успешно отправлено в чат {chat_id}, attempt {attempt + 1}")
            return message
            
        except Exception as e:
            error_msg = str(e).lower()
            if "flood control" in error_msg or "too many requests" in error_msg:
                # Extract retry time if available
                retry_after = RETRY_DELAY
                if "retry after" in error_msg:
                    try:
                        retry_match = re.search(r'retry after (\d+)', error_msg)
                        if retry_match:
                            retry_after = int(retry_match.group(1)) + 1
                    except:
                        pass
                
                logging.warning(f"⚠️ Flood control для чата {chat_id}, attempt {attempt + 1}/{MAX_RETRIES}, ждем {retry_after} секунд")
                await asyncio.sleep(retry_after)
                
                if attempt == MAX_RETRIES - 1:
                    logging.error(f"❌ Не удалось отправить сообщение в чат {chat_id} после {MAX_RETRIES} попыток")
                    return None
            else:
                logging.error(f"❌ Ошибка отправки сообщения в чат {chat_id}: {e}")
                if attempt == MAX_RETRIES - 1:
                    return None
                await asyncio.sleep(RETRY_DELAY)
    
    return None


async def safe_reply_message(message: Message, text: str, **kwargs) -> Optional[Message]:
    """
    Safely reply to message with flood control and retry logic
    """
    for attempt in range(MAX_RETRIES):
        try:
            # Add delay between messages to avoid flood control
            if attempt > 0:
                await asyncio.sleep(MESSAGE_DELAY)
            
            reply_message = await message.reply(text=text, **kwargs)
            logging.info(f"✅ Ответ успешно отправлен на сообщение {message.message_id}, attempt {attempt + 1}")
            return reply_message
            
        except Exception as e:
            error_msg = str(e).lower()
            if "flood control" in error_msg or "too many requests" in error_msg:
                # Extract retry time if available
                retry_after = RETRY_DELAY
                if "retry after" in error_msg:
                    try:
                        retry_match = re.search(r'retry after (\d+)', error_msg)
                        if retry_match:
                            retry_after = int(retry_match.group(1)) + 1
                    except:
                        pass
                
                logging.warning(f"⚠️ Flood control при ответе на сообщение {message.message_id}, attempt {attempt + 1}/{MAX_RETRIES}, ждем {retry_after} секунд")
                await asyncio.sleep(retry_after)
                
                if attempt == MAX_RETRIES - 1:
                    logging.error(f"❌ Не удалось ответить на сообщение {message.message_id} после {MAX_RETRIES} попыток")
                    return None
            else:
                logging.error(f"❌ Ошибка ответа на сообщение {message.message_id}: {e}")
                if attempt == MAX_RETRIES - 1:
                    return None
                await asyncio.sleep(RETRY_DELAY)
    
    return None


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











def subscribed_keyboard() -> InlineKeyboardBuilder:
    """Create inline keyboard with subscription button and channel link"""
    kb = InlineKeyboardBuilder()
    
    # Channel link button
    if CHANNEL_LINK:
        kb.button(text="📺 Obuna bo'lish", url=CHANNEL_LINK)
    elif isinstance(CHANNEL_ID, str) and CHANNEL_ID.startswith('@'):
        kb.button(text="📺 Obuna bo'lish", url=f"https://t.me/{CHANNEL_ID[1:]}")
    else:
        kb.button(text="📺 Obuna bo'lish", url=f"https://t.me/c/{str(CHANNEL_ID)[4:]}/1")
    
    # Universal subscription confirmation button (без привязки к пользователю)
    kb.button(text="✅ Men obuna bo'ldim", callback_data="i_subscribed")
    
    kb.adjust(1)  # One button per row
    return kb


async def handle_new_member(bot: Bot, chat_id: int, user_id: int, message: Message, user_info: dict = None) -> None:
    """Common logic for handling new members"""
    logging.info(f"🔍 Обнаружен новый участник: user_id={user_id} в чате chat_id={chat_id}")
    
    # Skip if this is the bot itself
    if user_id == bot.id:
        logging.info(f"🤖 Пропускаю самого бота: user_id={user_id}")
        return
        
    # Check subscription
    logging.info(f"📋 Проверяю подписку для user_id={user_id} в канале {CHANNEL_ID}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Статус подписки для user_id={user_id}: {'✅ ПОДПИСАН' if is_sub else '❌ НЕ ПОДПИСАН'}")
    
    if is_sub:
        logging.info(f"✅ Пользователь {user_id} уже подписан, разрешаю доступ")
        return

    # Check if user is chat owner (can't be restricted)
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        member_status = getattr(member, "status", "member")
        logging.info(f"👑 Статус пользователя {user_id} в группе: {member_status}")
        
        if member_status == "creator":
            # Chat owner - skip muting
            logging.info(f"👑 Пропускаю владельца группы {user_id} - нельзя ограничить")
            return
    except Exception as e:
        logging.warning(f"⚠️ Не удалось получить статус участника для пользователя {user_id}: {e}")

    # Mute user and send instruction
    logging.info(f"🔇 Мутирую пользователя {user_id} за отсутствие подписки")
    try:
        await mute_user(bot, chat_id, user_id)
        logging.info(f"✅ Успешно замьютил пользователя {user_id}")
    except Exception as e:
        logging.error(f"❌ Не удалось замьютить пользователя {user_id}: {e}")

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
        # Проверяем, существует ли сообщение для ответа
        try:
            await bot.get_message(chat_id, message.message_id)
        except Exception:
            logging.warning(f"⚠️ Сообщение {message.message_id} недоступно для ответа, отправляю без reply")
            sent_msg = await safe_send_message(
                bot, chat_id, text,
                reply_markup=subscribed_keyboard().as_markup(),
                disable_web_page_preview=True,
            )
        else:
            # Try to reply first, fallback to new message if reply fails
            try:
                sent_msg = await message.reply(
                    text,
                    reply_markup=subscribed_keyboard().as_markup(),
                    disable_web_page_preview=True,
                )
            except Exception:
                logging.warning(f"⚠️ Не удалось ответить на сообщение {message.message_id}, отправляю новое")
                sent_msg = await safe_send_message(
                    bot, chat_id, text,
                    reply_markup=subscribed_keyboard().as_markup(),
                    disable_web_page_preview=True,
                )
        
        if sent_msg:
            logging.info(f"📝 Foydalanuvchi {user_id} uchun obuna tugmasi bilan xabarni yubording, message_id={sent_msg.message_id}")
            
                    # Автопроверки и напоминания отключены по требованию
        else:
            logging.error(f"❌ Foydalanuvchi {user_id} uchun xabarni obuna tugmasi bilan yuborib bo'lmadi")
        
    except Exception as e:
        logging.error(f"❌ Foydalanuvchi {user_id} uchun xabarni obuna tugmasi bilan yuborib bo'lmadi: {e}")


async def send_daily_check_report(bot: Bot, checked_count: int, muted_count: int, already_muted_count: int, unsubscribed_users: list) -> None:
    """Send daily check report to channel owner"""
    try:
        # Try to get channel owner info
        if not CHANNEL_ID:
            logging.warning("⚠️ CHANNEL_ID not set, cannot send report to owner")
            return
        
        # Get channel info to find owner
        try:
            chat_info = await bot.get_chat(CHANNEL_ID)
            if not chat_info:
                logging.warning("⚠️ Could not get channel info")
                return
        except Exception as e:
            logging.warning(f"⚠️ Could not get channel info: {e}")
            return
        
        # Try to find channel owner
        owner_id = None
        
        # Method 1: Try to get from chat info
        if hasattr(chat_info, 'id') and chat_info.id:
            try:
                # Get chat administrators to find owner
                admins = await bot.get_chat_administrators(CHANNEL_ID)
                for admin in admins:
                    if admin.status == "creator":
                        owner_id = admin.user.id
                        break
            except Exception as e:
                logging.warning(f"⚠️ Could not get channel admins: {e}")
        
        # Method 2: If we have a specific owner ID in environment, use it
        # You can add OWNER_ID to your .env file
        if not owner_id:
            import os
            owner_id = os.getenv('OWNER_ID')
            if owner_id:
                try:
                    owner_id = int(owner_id)
                except ValueError:
                    owner_id = None
        
        if not owner_id:
            logging.warning("⚠️ Could not determine channel owner ID, skipping report")
            return
        
        # Prepare report message
        report_text = (
            f"📊 KUNLIK OBUNA TEKSHIRISH HISOBOTI\n\n"
            f"📅 Sana: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"👥 Guruh: {GROUP_ID}\n\n"
            f"📋 NATIJALAR:\n"
            f"✅ Tekshirilgan: {checked_count} foydalanuvchi\n"
            f"🔇 Yangi muxtalif qilingan: {muted_count} foydalanuvchi\n"
            f"🔇 Oldin muxtalif qilingan: {already_muted_count} foydalanuvchi\n"
            f"❌ Obuna emas: {len(unsubscribed_users)} foydalanuvchi\n\n"
        )
        
        if unsubscribed_users:
            report_text += f"📝 OBUNA EMAS FOYDALANUVCHILAR:\n\n"
            
            # Group users by status for better readability
            for i, user in enumerate(unsubscribed_users[:50], 1):  # Limit to 50 users
                user_display = "Foydalanuvchi"
                if user['username']:
                    user_display = f"@{user['username']}"
                elif user['first_name']:
                    user_display = user['first_name']
                    if user['last_name']:
                        user_display += f" {user['last_name']}"
                
                report_text += f"{i}. {user_display} (ID: {user['id']})\n"
            
            if len(unsubscribed_users) > 50:
                report_text += f"\n... va {len(unsubscribed_users) - 50} ta boshqa foydalanuvchi\n"
        else:
            report_text += "🎉 Barcha foydalanuvchilar obuna bo'lgan!"
        
        # Send report to owner
        try:
            # Проверяем, существует ли чат для отправки отчета
            try:
                await bot.get_chat(owner_id)
            except Exception:
                logging.warning(f"⚠️ Чат {owner_id} недоступен, пропускаю отправку отчета")
                return
            
            await safe_send_message(
                bot, owner_id, report_text,
                parse_mode="HTML"
            )
            logging.info(f"📊 Daily check report sent to channel owner {owner_id}")
        except Exception as e:
            logging.error(f"❌ Failed to send report to owner {owner_id}: {e}")
            
            # If DM fails, try to send to channel itself
            try:
                # Проверяем, существует ли канал для отправки отчета
                try:
                    await bot.get_chat(CHANNEL_ID)
                except Exception:
                    logging.warning(f"⚠️ Канал {CHANNEL_ID} недоступен, пропускаю отправку отчета")
                    return
                
                await safe_send_message(
                    bot, CHANNEL_ID, report_text,
                    parse_mode="HTML"
                )
                logging.info(f"📊 Daily check report sent to channel {CHANNEL_ID} instead of owner")
            except Exception as e2:
                logging.error(f"❌ Failed to send report to channel {CHANNEL_ID}: {e2}")
        
    except Exception as e:
        logging.error(f"❌ Error sending daily check report: {e}")


async def daily_check_all_members(bot: Bot) -> None:
    """Daily check all group members for subscription status"""
    if not GROUP_ID:
        logging.info("⚠️ GROUP_ID not set, skipping daily check")
        return
    
    try:
        logging.info(f"🔄 Starting daily subscription check for group {GROUP_ID}")
        
        # Note: Telegram API doesn't allow bots to get full member list
        # We'll check administrators and send a general reminder to the group
        # Users will be checked individually when they become active
        
        try:
            # Get chat administrators
            admins = await bot.get_chat_administrators(GROUP_ID)
            logging.info(f"📋 Found {len(admins)} administrators in group {GROUP_ID}")
            
            checked_count = 0
            muted_count = 0
            already_muted_count = 0
            unsubscribed_users = []
            
            for admin in admins:
                user_id = admin.user.id
                
                # Skip bot itself
                if user_id == bot.id:
                    continue
                    
                # Skip chat owner (creator)
                if admin.status == "creator":
                    logging.info(f"👑 Skipping group owner {user_id}")
                    continue
                
                checked_count += 1
                logging.info(f"🔍 Checking subscription for admin {user_id} ({admin.user.first_name or 'Unknown'})")
                
                # Check subscription
                is_sub = await is_user_subscribed(bot, user_id)
                
                if not is_sub:
                    # Collect user info for report
                    user_info = {
                        'id': user_id,
                        'username': admin.user.username,
                        'first_name': admin.user.first_name,
                        'last_name': admin.user.last_name,
                        'status': admin.status
                    }
                    unsubscribed_users.append(user_info)
                    
                    # Check if user is already muted
                    try:
                        current_member = await bot.get_chat_member(GROUP_ID, user_id)
                        if hasattr(current_member, 'is_restricted') and current_member.is_restricted:
                            already_muted_count += 1
                            logging.info(f"🔇 Admin {user_id} is already muted, skipping")
                            continue
                    except Exception as e:
                        logging.warning(f"⚠️ Could not check current status of admin {user_id}: {e}")
                    
                    # Mute admin
                    try:
                        await mute_user(bot, GROUP_ID, user_id)
                        muted_count += 1
                        
                        # Get user display name
                        user_display_name = "Foydalanuvchi"
                        if admin.user.username:
                            user_display_name = f"@{admin.user.username}"
                        elif admin.user.first_name:
                            user_display_name = admin.user.first_name
                            if admin.user.last_name:
                                user_display_name += f" {admin.user.last_name}"
                        
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
                        keyboard = subscribed_keyboard()
                        
                        # Send message using safe function
                        sent_msg = await safe_send_message(
                            bot, GROUP_ID, notification_text,
                            reply_markup=keyboard.as_markup(),
                            disable_web_page_preview=True,
                        )
                        
                        logging.info(f"📝 Sent daily check notification to admin {user_id} ({user_display_name}), message_id={sent_msg.message_id}")
                        
                        # Автопроверки и напоминания отключены по требованию
                        
                    except Exception as e:
                        logging.error(f"❌ Failed to mute admin {user_id} during daily check: {e}")
                else:
                    logging.info(f"✅ Admin {user_id} is subscribed, no action needed")
                
                # Добавляем задержку между проверками администраторов
                await asyncio.sleep(1.0)  # Задержка 1 секунда между каждым администратором
            
            # Убираем отправку общего напоминания в группу - эта информация скрыта от участников
            # if len(unsubscribed_users) > 0:
            #     general_reminder = (
            #         f"📢 KUNLIK ESDA QOLING!\n\n"
            #         f"🔴 Guruhda {len(unsubscribed_users)} ta foydalanuvchi kanalga obuna emas!\n\n"
            #         f"📋 Eslatma:\n"
            #         f"• Kanalga obuna bo'lmagan foydalanuvchilar ovozsiz qilindi\n"
            #         f"• Obuna bo'lish uchun yuqoridagi xabarlardagi tugmalarni bosing\n"
            #         f"• Obuna bo'lgandan so'ng \"✅ Men obuna bo'ldim\" tugmasini bosing\n\n"
            #         f"💡 Barcha foydalanuvchilar kanalga obuna bo'lishi shart!"
            #     )
            #     
            #     try:
            #         sent_reminder = await bot.send_message(
            #             chat_id=GROUP_ID,
            #             text=general_reminder,
            #             disable_web_page_preview=True
            #         )
            #         logging.info(f"📢 Sent general reminder to group, message_id={sent_reminder.message_id}")
            #         
            #         # Auto-delete general reminder after 1 hour
            #         asyncio.create_task(delete_message_after(bot, GROUP_ID, sent_reminder.message_id, 3600))
            #         
            #     except Exception as e:
            #         logging.error(f"❌ Failed to send general reminder: {e}")
            
        except Exception as e:
            logging.error(f"❌ Failed to get chat administrators: {e}")
            return
        
        # Send report to channel owner
        await send_daily_check_report(bot, checked_count, muted_count, already_muted_count, unsubscribed_users)
        
        logging.info(f"✅ Daily check completed: {checked_count} admins checked, {muted_count} newly muted, {already_muted_count} already muted")
        
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
    logging.info(f"👥 Обнаружены новые участники в чате chat_id={message.chat.id} в группе {GROUP_ID}")
    
    if GROUP_ID is not None and message.chat.id != GROUP_ID:
        logging.info(f"⚠️ Чат {message.chat.id} переадресуем - группа {GROUP_ID} отличается")
        return

    if not message.new_chat_members:
        logging.info("⚠️ В чате не обнаружены новые участники")
        return

    logging.info(f"📋 {len(message.new_chat_members)} новых участников, которые нужно обработать")
    for user in message.new_chat_members:
        logging.info(f"👤 Обрабатываю нового участника: {user.first_name} (@{user.username}) user_id={user.id}")
        user_info = {
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name
        }
        await handle_new_member(bot, message.chat.id, user.id, message, user_info)


@router.chat_join_request()
async def on_chat_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    """Handle join requests (when group requires approval)"""
    logging.info(f"📝 Запрос на вступление user_id={event.from_user.id} chat_id={event.chat.id} в группу {GROUP_ID}")
    
    if GROUP_ID is not None and event.chat.id != GROUP_ID:
        logging.info(f"⚠️ Чат {event.chat.id} переадресуем - группа {GROUP_ID} отличается")
        return

    user_id = event.from_user.id
    logging.info(f"📋 Проверяю подписку для user_id={user_id}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Статус подписки для user_id={user_id}: {'✅ ПОДПИСАН' if is_sub else '❌ НЕ ПОДПИСАН'}")
    
    if is_sub:
        # Approve the request
        logging.info(f"✅ Запрос на вступление {user_id} принят")
        await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=user_id)
    else:
        # Decline the request
        logging.info(f"❌ Запрос на вступление {user_id} отклонен")
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
                f"🔴 DIQQAT! Sizning kirish so'ralishi rad etildi!\n\n"
                f"👤 {user_display_name}, guruhdaga kirish uchun:\n\n"
                f"📋 QADAMMA-QADAM KO'RSATMALAR:\n\n"
                f"1️⃣ Linkni bosing: {CHANNEL_LINK}\n"
                f"2️⃣ \"Obuna bo'lish\" / \"Join\" tugmasini bosing\n"
                f"3️⃣ Guruhga qayting\n"
                f"4️⃣ Yangi so'ralishni yuboring\n"
                f"5️⃣ Tayyor! Avtomatik kirishga ruxsat beriladi\n\n"
                f"💡 Obuna bo'lgandan so'ng so'ralish avtomatik ravishda qabul qilinadi!"
            )
        else:
            text = (
                f"🔴 DIQQAT! Sizning kirish so'ralishi rad etildi!\n\n"
                f"👤 {user_display_name}, guruhdaga kirish uchun:\n\n"
                f"📋 QADAMMA-QADAM KO'RSATMALAR:\n\n"
                f"1️⃣ Obligatsion kanalga obuna bo'ling\n"
                f"2️⃣ Guruhga qayting\n"
                f"3️⃣ Yangi so'ralishni yuboring\n"
                f"4️⃣ Tayyor! Avtomatik kirishga ruxsat beriladi\n\n"
                f"💡 Obuna bo'lgandan so'ng so'ralish avtomatik ravishda qabul qilinadi!"
            )
        try:
            # Проверяем, существует ли пользователь для отправки DM
            try:
                await bot.get_chat(user_id)
            except Exception:
                logging.warning(f"⚠️ Пользователь {user_id} недоступен для DM, пропускаю отправку")
                return
            
            await safe_send_message(bot, user_id, text)
            logging.info(f"📱 Уведомление пользователю {user_id} отправлено в DM")
        except Exception as e:
            logging.warning(f"⚠️ Не удалось отправить сообщение пользователю {user_id} в DM: {e}")


@router.callback_query(F.data == "i_subscribed")
async def on_subscribed_click(callback: CallbackQuery, bot: Bot) -> None:
    logging.info(f"🔘 Универсальная кнопка 'Подписался' нажата пользователем user_id={callback.from_user.id}")
    
    chat = callback.message.chat if callback.message else None
    if chat is None:
        logging.warning("⚠️ Нет информации о чате")
        await callback.answer()
        return

    if GROUP_ID is not None and chat.id != GROUP_ID:
        logging.info(f"⚠️ Кнопка перешла к чату {chat.id}, {GROUP_ID} ожидалось")
        await callback.answer()
        return

    user_id = callback.from_user.id
    logging.info(f"🔍 Обрабатываю нажатие универсальной кнопки пользователем user_id={user_id}")
    
    # Проверяем подписку нажавшего пользователя
    logging.info(f"📋 Проверяю подписку для user_id={user_id}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Статус подписки для user_id={user_id}: {'✅ ПОДПИСАН' if is_sub else '❌ НЕ ПОДПИСАН'}")
    
    if is_sub:
        try:
            # Проверяем, является ли пользователь владельцем чата (нельзя ограничить)
            member = await bot.get_chat_member(chat.id, user_id)
            member_status = getattr(member, "status", "member")
            logging.info(f"👑 Статус пользователя {user_id} в группе: {member_status}")
            
            if member_status == "creator":
                # Владелец чата - просто отправляем приветственное сообщение без размучения
                logging.info(f"👑 Владелец группы {user_id} подтвердил подписку")
                await callback.answer("Подписка подтверждена")
                return
            
            # Проверяем, замучен ли пользователь
            if hasattr(member, 'is_restricted') and member.is_restricted:
                logging.info(f"🔓 Размучиваю пользователя {user_id} после подтверждения подписки")
                await unmute_user(bot, chat.id, user_id)
                logging.info(f"✅ Успешно размутил пользователя {user_id}")
                
                # Отправляем приветственное сообщение
                welcome_text = "🎉 Guruhga xush kelibsiz!\n\n✅ Endi xabar yozishingiz mumkin."
                
                try:
                    # Try to reply first, fallback to new message if reply fails
                    try:
                        sent = await bot.send_message(
                            chat_id=chat.id,
                            text=welcome_text,
                            reply_to_message_id=callback.message.message_id,
                        )
                    except Exception:
                        logging.warning(f"⚠️ Не удалось ответить на сообщение {callback.message.message_id}, отправляю новое")
                        sent = await safe_send_message(bot, chat.id, welcome_text)
                    
                    if sent:
                        logging.info(f"📝 Отправлено приветственное сообщение пользователю {user_id}, message_id={sent.message_id}")
                        
                        # Планируем удаление приветственного сообщения
                        asyncio.create_task(delete_message_after(bot, chat.id, sent.message_id, 10))
                    else:
                        logging.error(f"❌ Не удалось отправить приветственное сообщение пользователю {user_id}")
                    
                except Exception as e:
                    logging.error(f"❌ Не удалось отправить приветственное сообщение пользователю {user_id}: {e}")
                
                # Удаляем сообщение с кнопкой (которое нажал пользователь)
                try:
                    await bot.delete_message(chat_id=chat.id, message_id=callback.message.message_id)
                    logging.info(f"🗑️ Удалено сообщение с кнопкой {callback.message.message_id} для пользователя {user_id}")
                except Exception as e:
                    logging.error(f"❌ Не удалось удалить сообщение с кнопкой: {e}")
                
                await callback.answer("Obuna tasdiqlandi! Siz ovozsiz qilindingiz.")
                logging.info(f"✅ Подписка подтверждена и пользователь {user_id} размучен")
                
            else:
                # Пользователь не замучен
                logging.info(f"ℹ️ Пользователь {user_id} не замучен, но подписан")
                await callback.answer("Siz allaqachon ovozsiz emassiz va obuna bo'lgansiz!")
                
        except Exception as e:
            logging.error(f"❌ Не удалось обработать нажатие кнопки для пользователя {user_id}: {e}")
            await callback.answer("Xatolik yuz berdi, qaytadan urinib ko'ring")
            
    else:
        logging.warning(f"⚠️ Пользователь {user_id} не подписан")
        await callback.answer("Siz hali kanalga obuna bo'lmagansiz! Avval obuna bo'ling, keyin tugmani bosing.", show_alert=True)


@router.message(CommandStart())
async def on_start(message: Message, bot: Bot) -> None:
    """Handle /start command"""
    logging.info(f"🚀 Команда /start пользователя user_id={message.from_user.id} в группе {GROUP_ID}")
    
    if CHANNEL_LINK:
        text = (
            f"👋 Salom, {message.from_user.first_name or 'foydalanuvchi'}!\n\n"
            f"📺 Bu bot kanal obuna tekshirish uchun.\n\n"
            f"📋 BOT QANDAY ISHLASHI:\n\n"
            f"1️⃣ Guruhga qo'shiling\n"
            f"2️⃣ Bot sizning obunangizni tekshiradi\n"
            f"3️⃣ Agar obuna emas bo'lsangiz, muxtalif qilinasiz\n"
            f"4️⃣ Kanalga obuna bo'ling: {CHANNEL_LINK}\n"
            f"5️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
            f"6️⃣ Tayyor! Guruhda yozishingiz mumkin\n\n"
            f"💡 Obuna holatingizni tekshirish uchun /check buyrug'ini ishlating"
        )
    else:
        text = (
            f"👋 Salom, {message.from_user.first_name or 'foydalanuvchi'}!\n\n"
            f"📺 Bu bot obligatsion kanal uchun.\n\n"
            f"📋 BOT QANDAY ISHLASHI:\n\n"
            f"1️⃣ Guruhga qo'shiling\n"
            f"2️⃣ Bot sizning obunangizni tekshiradi\n"
            f"3️⃣ Agar obuna emas bo'lsangiz, muxtalif qilinasiz\n"
            f"4️⃣ Obligatsion kanalga obuna bo'ling\n"
            f"5️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
            f"6️⃣ Tayyor! Guruhda yozishingiz mumkin\n\n"
            f"💡 Obuna holatingizni tekshirish uchun /check buyrug'ini ishlating"
        )
    
    # Проверяем, существует ли пользователь для отправки приветствия
    try:
        await bot.get_chat(message.from_user.id)
    except Exception:
        logging.warning(f"⚠️ Пользователь {message.from_user.id} недоступен для отправки приветствия")
        return
    
    await safe_reply_message(message, text)
    logging.info(f"📝 Отправлено приветственное сообщение пользователю {message.from_user.id}")


@router.message(Command("check"))
async def on_check(message: Message, bot: Bot) -> None:
    """Handle /check command"""
    logging.info(f"🔍 Команда /check пользователя user_id={message.from_user.id} в группе {GROUP_ID}")
    
    if message.chat.type != "private":
        logging.info(f"⚠️ Команда /check использована в личном чате, переадресуем")
        return
    
    user_id = message.from_user.id
    logging.info(f"📋 Проверяю подписку для user_id={user_id}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Статус подписки для user_id={user_id}: {'✅ ПОДПИСАН' if is_sub else '❌ НЕ ПОДПИСАН'}")
    
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
                f"5️⃣ Tayyor! Endi siz yozishingiz mumkin\n\n"
                f"💡 Obuna bo'lgandan so'ng qayta tekshirish uchun /check buyrug'ini ishlating"
            )
        else:
            text = (
                f"❌ Siz hali obligatsion kanalga obuna emassiz!\n\n"
                f"📋 NIMA QILISHI:\n\n"
                f"1️⃣ Obligatsion kanalga obuna bo'ling\n"
                f"2️⃣ Guruhga qayting\n"
                f"3️⃣ \"✅ Men obuna bo'ldim\" tugmasini bosing\n"
                f"4️⃣ Tayyor! Endi siz yozishingiz mumkin\n\n"
                f"💡 Obuna bo'lgandan so'ng qayta tekshirish uchun /check buyrug'ini ishlating"
            )
    
    # Проверяем, существует ли пользователь для отправки результата
    try:
        await bot.get_chat(user_id)
    except Exception:
        logging.warning(f"⚠️ Пользователь {user_id} недоступен для отправки результата")
        return
    
    await safe_reply_message(message, text)
    logging.info(f"📝 Отправлен статус подписки для пользователя {user_id}")


@router.message(Command("force_check"))
async def on_force_check(message: Message, bot: Bot) -> None:
    """Handle /force_check command - force check all group members"""
    logging.info(f"🔍 Команда /force_check от пользователя {message.from_user.id} в группе {GROUP_ID}")
    
    if message.chat.type != "private":
        logging.info(f"⚠️ Команда /force_check использована не в личном чате, пропускаем")
        return
    
    user_id = message.from_user.id
    
    # Проверяем, является ли пользователь владельцем бота (вы можете изменить логику)
    # На данный момент разрешаем любому пользователю в личном чате использовать эту команду
    # Вы можете добавить конкретные проверки ID пользователя здесь, если это необходимо
    
    if not GROUP_ID:
        await message.answer("❌ GROUP_ID sozlanmagan, majburiy tekshirish amalga oshirilmaydi")
        return
    
    await safe_reply_message(message, "🔄 Barcha guruh a'zolarini majburiy tekshirishni boshlayman... Bu biroz vaqt olishi mumkin.")
    
    try:
        # Запускаем функцию ежедневной проверки
        await daily_check_all_members(bot)
        
        # Проверяем, существует ли пользователь для отправки результата
        try:
            await bot.get_chat(user_id)
        except Exception:
            logging.warning(f"⚠️ Пользователь {user_id} недоступен для отправки результата")
            return
        
        # Получаем список не подписанных пользователей для отчета
        try:
            admins = await bot.get_chat_administrators(GROUP_ID)
            unsubscribed_users = []
            
            for admin in admins:
                user_id_admin = admin.user.id
                
                # Skip bot itself and chat owner
                if user_id_admin == bot.id or admin.status == "creator":
                    continue
                
                # Check subscription
                is_sub = await is_user_subscribed(bot, user_id_admin)
                
                if not is_sub:
                    user_info = {
                        'id': user_id_admin,
                        'username': admin.user.username,
                        'first_name': admin.user.first_name,
                        'last_name': admin.user.last_name,
                        'status': admin.status
                    }
                    unsubscribed_users.append(user_info)
            
            # Формируем отчет о не подписанных пользователях
            if unsubscribed_users:
                report_text = (
                    f"📊 MAJBURIY TEKSHIRISH HISOBOTI\n\n"
                    f"📅 Sana: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"👥 Guruh: {GROUP_ID}\n\n"
                    f"❌ OBUNA EMAS FOYDALANUVCHILAR: {len(unsubscribed_users)} ta\n\n"
                )
                
                for i, user in enumerate(unsubscribed_users, 1):
                    user_display = "Foydalanuvchi"
                    if user['username']:
                        user_display = f"@{user['username']}"
                    elif user['first_name']:
                        user_display = user['first_name']
                        if user['last_name']:
                            user_display += f" {user['last_name']}"
                    
                    report_text += f"{i}. {user_display} (ID: {user['id']})\n"
                
                await safe_reply_message(message, report_text)
            else:
                await safe_reply_message(message, "✅ Barcha foydalanuvchilar obuna bo'lgan!")
                
        except Exception as e:
            logging.error(f"❌ Ошибка при получении списка не подписанных пользователей: {e}")
            await safe_reply_message(message, "✅ Majburiy tekshirish muvaffaqiyatli yakunlandi!")
        
    except Exception as e:
        logging.error(f"❌ Ошибка при принудительной проверке: {e}")
        
        # Проверяем, существует ли пользователь для отправки ошибки
        try:
            await bot.get_chat(user_id)
        except Exception:
            logging.warning(f"⚠️ Пользователь {user_id} недоступен для отправки ошибки")
            return
        
        await safe_reply_message(message, f"❌ Majburiy tekshirishda xatolik yuz berdi: {e}")


@router.message(Command("id"))
async def on_id(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    chat = message.chat
    logging.info(f"🆔 Команда /id пользователя user_id={user_id} chat_id={chat.id}, chat_type={chat.type} в группе {GROUP_ID}")
    
    # Отвечаем только в группах/супергруппах
    if chat.type not in ("group", "supergroup"):
        logging.info(f"⚠️ Команда /id использована в неправильном типе чата: {chat.type}")
        await message.answer("Bu buyruq faqat guruhlarda ishlaydi.")
        return

    # Дополнительно требуем, чтобы пользователь был администратором/создателем (чтобы не спамить)
    try:
        member = await bot.get_chat_member(chat.id, user_id)
        member_status = getattr(member, "status", "member")
        logging.info(f"👑 Статус пользователя {user_id} в группе: {member_status}")
        
        if member_status not in ("administrator", "creator"):
            logging.warning(f"🚫 Неверный пользователь {user_id} пытался использовать команду /id")
            await message.answer("Bu buyruq faqat guruh administratorlari uchun mavjud.")
            return
    except Exception as e:
        logging.warning(f"⚠️ Не удалось проверить статус пользователя {user_id} для команды /id: {e}")

    # Проверяем, существует ли пользователь для отправки результата
    try:
        await bot.get_chat(user_id)
    except Exception:
        logging.warning(f"⚠️ Пользователь {user_id} недоступен для отправки результата")
        return

    await safe_reply_message(message, f"chat.id = {chat.id}\nchat.type = {chat.type}")
    logging.info(f"✅ Chat ID информация отправлена администратору {user_id}: chat.id={chat.id}, chat.type={chat.type}")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    # Отбрасываем ожидающие обновления
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем бота
    logging.info("🚀 Запускаем бота...")
    
    # Автопланировщик ежедневной проверки отключен
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())