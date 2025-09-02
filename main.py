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
    logging.info(f"⏰ Запланировано удаление сообщения {message_id} через {delay_seconds} секунд")
    try:
        await asyncio.sleep(delay_seconds)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logging.info(f"✅ Успешно удалил сообщение {message_id}")
    except Exception as e:
        logging.warning(f"⚠️ Не удалось удалить сообщение {message_id}: {e}")


def subscribed_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Obuna bo'ldim", callback_data="i_subscribed")
    kb.adjust(1)
    return kb


async def handle_new_member(bot: Bot, chat_id: int, user_id: int, message: Message) -> None:
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
        logging.info(f"📝 Отправил сообщение с кнопкой подписки пользователю {user_id}, message_id={sent_msg.message_id}")
    except Exception as e:
        logging.error(f"❌ Не удалось отправить сообщение с кнопкой пользователю {user_id}: {e}")


@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message, bot: Bot) -> None:
    """Handle new members joining via invite links"""
    logging.info(f"👥 Обнаружено событие новых участников в чате chat_id={message.chat.id}")
    
    if GROUP_ID is not None and message.chat.id != GROUP_ID:
        logging.info(f"⚠️ Пропускаю чат {message.chat.id} - не целевая группа {GROUP_ID}")
        return

    if not message.new_chat_members:
        logging.info("⚠️ Новых участников в сообщении не найдено")
        return

    logging.info(f"📋 Обрабатываю {len(message.new_chat_members)} новых участников")
    for user in message.new_chat_members:
        logging.info(f"👤 Обрабатываю нового участника: {user.first_name} (@{user.username}) user_id={user.id}")
        await handle_new_member(bot, message.chat.id, user.id, message)


@router.chat_join_request()
async def on_chat_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    """Handle join requests (when group requires approval)"""
    logging.info(f"📝 Заявка на вступление от user_id={event.from_user.id} в чат chat_id={event.chat.id}")
    
    if GROUP_ID is not None and event.chat.id != GROUP_ID:
        logging.info(f"⚠️ Пропускаю заявку в чате {event.chat.id} - не целевая группа {GROUP_ID}")
        return

    user_id = event.from_user.id
    logging.info(f"📋 Проверяю подписку для заявки от user_id={user_id}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Статус подписки для заявки от user_id={user_id}: {'✅ ПОДПИСАН' if is_sub else '❌ НЕ ПОДПИСАН'}")
    
    if is_sub:
        # Approve the request
        logging.info(f"✅ Одобряю заявку от подписанного пользователя {user_id}")
        await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=user_id)
    else:
        # Decline the request
        logging.info(f"❌ Отклоняю заявку от неподписанного пользователя {user_id}")
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
            logging.info(f"📱 Отправил уведомление в ЛС пользователю {user_id}")
        except Exception as e:
            logging.warning(f"⚠️ Не удалось отправить ЛС пользователю {user_id}: {e}")


@router.callback_query(F.data == "i_subscribed")
async def on_subscribed_click(callback: CallbackQuery, bot: Bot) -> None:
    logging.info(f"🔘 Кнопка 'Obuna bo'ldim' нажата пользователем user_id={callback.from_user.id} в чате chat_id={callback.message.chat.id if callback.message else 'неизвестно'}")
    
    chat = callback.message.chat if callback.message else None
    if chat is None:
        logging.warning("⚠️ Нет информации о чате в колбэке")
        await callback.answer()
        return

    if GROUP_ID is not None and chat.id != GROUP_ID:
        logging.info(f"⚠️ Кнопка нажата в неправильном чате {chat.id}, ожидался {GROUP_ID}")
        await callback.answer()
        return

    user_id = callback.from_user.id
    logging.info(f"🔍 Обрабатываю нажатие кнопки от пользователя user_id={user_id}")
    
    # Check if this user is the one who was mentioned in the original message
    if callback.message and callback.message.reply_to_message:
        # Extract user ID from the mention in the original message
        mention_pattern = r'tg://user\?id=(\d+)'
        reply_text = callback.message.reply_to_message.text
        if reply_text:  # Check if text is not None
            match = re.search(mention_pattern, reply_text)
            if match:
                mentioned_user_id = int(match.group(1))
                logging.info(f"📝 Кнопка была предназначена для user_id={mentioned_user_id}, нажал user_id={user_id}")
                if user_id != mentioned_user_id:
                    logging.warning(f"🚫 Неправильный пользователь {user_id} нажал кнопку, предназначенную для {mentioned_user_id}")
                    await callback.answer("Bu tugma siz uchun emas!", show_alert=True)
                    return
                logging.info(f"✅ Правильный пользователь {user_id} нажал свою кнопку")
        else:
            logging.warning(f"⚠️ reply_to_message.text равен None для пользователя {user_id}")
    else:
        logging.info("ℹ️ Нет reply_to_message, продолжаю проверку подписки")

    logging.info(f"📋 Проверяю подписку для нажатия кнопки от пользователя user_id={user_id}")
    is_sub = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Статус подписки для нажатия кнопки от user_id={user_id}: {'✅ ПОДПИСАН' if is_sub else '❌ НЕ ПОДПИСАН'}")
    
    if is_sub:
        try:
            # Check if user is chat owner (can't be restricted)
            member = await bot.get_chat_member(chat.id, user_id)
            member_status = getattr(member, "status", "member")
            logging.info(f"👑 Статус пользователя {user_id} в группе: {member_status}")
            
            if member_status == "creator":
                # Chat owner - just send welcome message without unmuting
                logging.info(f"👑 Владелец группы {user_id} подтвердил подписку")
                await callback.answer("Obuna tasdiqlandi")
                return
            
            logging.info(f"🔓 Размучиваю пользователя {user_id} после подтверждения подписки")
            await unmute_user(bot, chat.id, user_id)
            logging.info(f"✅ Успешно размутил пользователя {user_id}")
        except Exception as e:
            logging.error(f"❌ Не удалось размутить пользователя {user_id}: {e}")
        
        # Reply to the original join message if available
        try:
            if callback.message and callback.message.reply_to_message:
                sent = await bot.send_message(
                    chat_id=chat.id,
                    text="Kirish ochildi. Xush kelibsiz!",
                    reply_to_message_id=callback.message.reply_to_message.message_id,
                )
                logging.info(f"📝 Отправил приветственное сообщение в ответ пользователю {user_id}, message_id={sent.message_id}")
            else:
                sent = await callback.message.answer("Kirish ochildi. Xush kelibsiz!")
                logging.info(f"📝 Отправил приветственное сообщение пользователю {user_id}, message_id={sent.message_id}")
            
            # Schedule deletion of the greeting too
            logging.info(f"⏰ Планирую удаление приветственного сообщения {sent.message_id} через 10 секунд")
            asyncio.create_task(delete_message_after(bot, chat.id, sent.message_id, 10))
        except Exception as e:
            logging.error(f"❌ Не удалось отправить приветственное сообщение пользователю {user_id}: {e}")
        
        # Schedule deletion of the subscribe prompt message (with the button)
        try:
            logging.info(f"⏰ Планирую удаление сообщения с кнопкой {callback.message.message_id} через 10 секунд")
            asyncio.create_task(delete_message_after(bot, chat.id, callback.message.message_id, 10))
        except Exception as e:
            logging.error(f"❌ Не удалось запланировать удаление сообщения с кнопкой: {e}")
        
        await callback.answer("Obuna tasdiqlandi")
        logging.info(f"✅ Подписка подтверждена для пользователя {user_id}")
    else:
        logging.warning(f"⚠️ Пользователь {user_id} нажал кнопку, но не подписан")
        await callback.answer("Siz hali obuna bo'lmaggansiz", show_alert=False)


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    logging.info(f"🚀 Команда /start от пользователя user_id={message.from_user.id} в чате chat_id={message.chat.id}")
    lines = [
        "Привет! Я проверяю подписку на канал перед отправкой сообщений в группе.",
    ]
    if CHANNEL_LINK:
        lines.append(f"Сначала подпишитесь на канал: {CHANNEL_LINK}")
    await message.answer("\n".join(lines))
    logging.info(f"✅ Отправил приветственное сообщение пользователю {message.from_user.id}")


@router.message(Command("check"))
async def on_check(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    logging.info(f"🔍 Команда /check от пользователя user_id={user_id} в чате chat_id={message.chat.id}")
    
    logging.info(f"📋 Проверяю подписку для команды /check от пользователя user_id={user_id}")
    subscribed = await is_user_subscribed(bot, user_id)
    logging.info(f"📊 Статус подписки для команды /check от user_id={user_id}: {'✅ ПОДПИСАН' if subscribed else '❌ НЕ ПОДПИСАН'}")
    
    if not subscribed:
        if CHANNEL_LINK:
            await message.answer(
                f"Вы ещё не подписаны. Подпишитесь: {CHANNEL_LINK} и нажмите кнопку в группе."
            )
            logging.info(f"📝 Отправил сообщение 'не подписан' пользователю {user_id}")
        else:
            await message.answer("Вы ещё не подписаны на обязательный канал. Подпишитесь и нажмите кнопку в группе.")
            logging.info(f"📝 Отправил сообщение 'не подписан' пользователю {user_id}")
        return

    await message.answer("Подписка найдена. Если вы были ограничены в группе — кнопка теперь откроет доступ.")
    logging.info(f"✅ Отправил подтверждение 'подписан' пользователю {user_id}")


@router.message(Command("id"))
async def on_id(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    chat = message.chat
    logging.info(f"🆔 Команда /id от пользователя user_id={user_id} в чате chat_id={chat.id}, тип_чата={chat.type}")
    
    # Отвечаем только в группах/супергруппах
    if chat.type not in ("group", "supergroup"):
        logging.info(f"⚠️ Команда /id использована в неправильном типе чата: {chat.type}")
        await message.answer("Эта команда работает только в группе.")
        return

    # Дополнительно потребуем, чтобы вызвал админ/создатель (чтоб не спамили)
    try:
        member = await bot.get_chat_member(chat.id, user_id)
        member_status = getattr(member, "status", "member")
        logging.info(f"👑 Статус пользователя {user_id} в группе: {member_status}")
        
        if member_status not in ("administrator", "creator"):
            logging.warning(f"🚫 Не-админ пользователь {user_id} попытался использовать команду /id")
            await message.answer("Команда доступна только администраторам группы.")
            return
    except Exception as e:
        logging.warning(f"⚠️ Не удалось проверить статус пользователя для команды /id: {e}")

    await message.answer(f"chat.id = {chat.id}\nchat.type = {chat.type}")
    logging.info(f"✅ Отправил информацию о ID чата админу {user_id}: chat.id={chat.id}, chat.type={chat.type}")


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