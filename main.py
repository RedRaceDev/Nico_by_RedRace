import asyncio
import os
import time
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from scraper import generate_posts_pack, get_f1_calendar

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set")

STATE = {
    "pub_mode": "DIRECT",
    "start_time": time.time(),
    "auto_interval": 14400,  # 4 часа
}

DIGEST_BUFFER = []
ADMIN_CHAT_ID = None
bot = None

async def send_crafted_post(target_chat, text, photo_url=None, with_publish_button=False):
    if not bot:
        return
    kb = None
    if with_publish_button:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🚀 ОПУБЛИКОВАТЬ В КАНАЛ", callback_data="pub_direct_action"))
    try:
        if photo_url:
            await bot.send_photo(target_chat, photo_url, caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await bot.send_message(target_chat, text, parse_mode="HTML", reply_markup=kb)
    except:
        try:
            await bot.send_message(target_chat, text, parse_mode="HTML", reply_markup=kb)
        except:
            pass

async def admin_panel(m):
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = m.chat.id
    uptime = time.time() - STATE["start_time"]
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("⚡️ Ручной скан", callback_data="force_scan"),
        InlineKeyboardButton("📅 Календарь гонок", callback_data="calendar")
    )
    status = (
        f"📋 <b>Nico PRO</b>\n"
        f"Аптайм: <code>{int(uptime//3600)}ч {int((uptime%3600)//60)}м</code>\n"
        f"Режим: <b>{STATE['pub_mode']}</b>\n"
        f"Авто-интервал: <b>{STATE['auto_interval']//3600} ч</b>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=kb)

async def manual_trigger(m):
    if m.text and m.text.startswith('/'):
        return
    status_msg = await bot.send_message(m.chat.id, "<code>Сбор данных...</code>", parse_mode="HTML")
    try:
        posts = await generate_posts_pack(m.text if m.text else "")
        if not posts:
            await bot.send_message(m.chat.id, "Нет свежих новостей.")
        else:
            for post in posts:
                await send_crafted_post(m.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
    except Exception as e:
        await bot.send_message(m.chat.id, f"🚨 Ошибка: {e}")
    await bot.delete_message(m.chat.id, status_msg.message_id)

async def handle_callbacks(call):
    if call.data == "force_scan":
        await bot.answer_callback_query(call.id, "Сканирую...")
        await manual_trigger(call.message)
    elif call.data == "calendar":
        cal = await get_f1_calendar(14)
        await bot.send_message(call.message.chat.id, cal, parse_mode="HTML")
        await bot.answer_callback_query(call.id)
    elif call.data == "pub_direct_action":
        try:
            if call.message.caption:
                await bot.send_photo("@RedRaceF1", call.message.photo[-1].file_id, caption=call.message.caption, parse_mode="HTML")
            else:
                await bot.send_message("@RedRaceF1", call.message.text, parse_mode="HTML")
            await bot.answer_callback_query(call.id, "Опубликовано!")
            await bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception as e:
            print(f"Publish error: {e}")
        return
    else:
        await bot.answer_callback_query(call.id)

async def auto_post_worker():
    while True:
        await asyncio.sleep(STATE['auto_interval'])
        if STATE["kill_switch"]:
            continue
        try:
            posts = await generate_posts_pack()
            for post in posts:
                if STATE["pub_mode"] == "DIRECT":
                    await send_crafted_post("@RedRaceF1", post["text"], post.get("photo_url"))
                await asyncio.sleep(3)
        except Exception as e:
            print(f"Auto post error: {e}")

async def polling_worker():
    while True:
        try:
            await bot.infinity_polling(timeout=30, request_timeout=30)
        except Exception as e:
            print(f"Polling error: {e}, reconnect in 10s")
            await asyncio.sleep(10)

def register_handlers(bot_instance):
    bot_instance.register_message_handler(admin_panel, commands=['admin'])
    bot_instance.register_message_handler(manual_trigger, func=lambda m: True, content_types=['text'])
    bot_instance.register_callback_query_handler(handle_callbacks, func=lambda call: True)

async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    register_handlers(bot)
    asyncio.create_task(auto_post_worker())
    asyncio.create_task(polling_worker())
    print("Nico PRO started on Render!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
