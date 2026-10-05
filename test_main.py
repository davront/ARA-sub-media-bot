"""Самопроверка логики без сети: python test_main.py"""
import os
import time

os.environ.setdefault("TOKEN", "123:test")
os.environ["CHANNEL_ID"] = "@my_channel"

from aiogram.types import Chat, User  # noqa: E402

import main  # noqa: E402

# Имя с HTML не должно ломать parse_mode=HTML и подменять ссылки
evil = User(id=1, is_bot=False, first_name='<a href="x">', last_name="& co")
assert main.display_name(evil) == "&lt;a href=&quot;x&quot;&gt; &amp; co", main.display_name(evil)
assert main.display_name(User(id=2, is_bot=False, first_name="A", username="nick")) == "@nick"

# Кнопка снимает только муты, выставленные ботом, и только пока они действуют
main.BOT_MUTED[(10, 1)] = time.monotonic() + 60
main.BOT_MUTED[(10, 2)] = time.monotonic() - 1
assert main.muted_by_bot(10, 1)
assert not main.muted_by_bot(10, 2)
assert not main.muted_by_bot(10, 3)

assert main.is_our_channel(Chat(id=-100, type="channel", username="My_Channel"))
assert not main.is_our_channel(Chat(id=-100, type="channel", username="other"))
assert main.CHANNEL_URL == "https://t.me/my_channel"

# left_chat_member должен стоять раньше общего обработчика сообщений
names = [h.callback.__name__ for h in main.router.message.handlers]
assert names.index("on_left_chat_member") < names.index("on_group_message"), names
assert names[-1] == "on_group_message", names

print("ok")
