import asyncio
import os
import time
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from scraper import generate_posts_pack, get_f1_calendar, chat_with_nico

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set")

STATE = {
    "pub_mode": "DIRECT",
    "start_time": time.time(),
    "auto_interval": 14400,
    "chat_mode": False  # Режим диалога с ИИ
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
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📰 Пост из новостей", callback_data="auto_post"),
        InlineKeyboardButton("💬 Режим диалога", callback_data="chat_mode"),
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("⚡️ Ручной скан", callback_data="force_scan")
    )
    
    status = (
        f"📋 <b>Nico PRO - Гоночный инженер</b>\n"
        f"<code>─────────────────────</code>\n"
        f"📊 Аптайм: <code>{int(uptime//3600)}ч {int((uptime%3600)//60)}м</code>\n"
        f"🎯 Режим: <b>{'💬 Чат' if STATE['chat_mode'] else '📰 Автопостинг'}</b>\n"
        f"⏱ Интервал: <b>{STATE['auto_interval']//3600} ч</b>\n"
        f"<code>─────────────────────</code>\n"
        f"💡 <b>Что умею:</b>\n"
        f"• Отвечать на вопросы о F1\n"
        f"• Искать новости и делать посты\n"
        f"• Показывать календарь гонок\n"
        f"• Генерировать посты по теме\n\n"
        f"<i>Просто напиши что хочешь узнать</i>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=kb)

async def manual_trigger(m):
    """Обработка сообщений - теперь ИИ сам решает, что делать"""
    user_text = m.text if m.text else ""
    
    # Команды не обрабатываем тут
    if user_text.startswith('/'):
        return
    
    status_msg = await bot.send_message(m.chat.id, "🤔 <i>Анализирую запрос...</i>", parse_mode="HTML")
    
    try:
        # Проверяем, хочет ли пользователь пост или просто вопрос
        if "пост" in user_text.lower() or "сделай пост" in user_text.lower() or "выложи" in user_text.lower():
            # Генерируем пост на тему
            posts = await generate_posts_pack(user_text)
            if posts:
                for post in posts[:2]:  # Максимум 2 поста
                    await send_crafted_post(m.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
            else:
                await bot.send_message(m.chat.id, "❌ Не удалось сгенерировать пост по этой теме")
        
        elif "новости" in user_text.lower() or "что нового" in user_text.lower():
            # Ищем новости
            posts = await generate_posts_pack("")
            if posts:
                for post in posts[:2]:
                    await send_crafted_post(m.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
            else:
                await bot.send_message(m.chat.id, "📭 Свежих новостей пока нет")
        
        else:
            # Обычный диалог - отвечаем как эксперт
            answer = await chat_with_nico(user_text)
            await bot.send_message(m.chat.id, answer, parse_mode="HTML")
            
    except Exception as e:
        await bot.send_message(m.chat.id, f"❌ Ошибка: {e}")
    
    await bot.delete_message(m.chat.id, status_msg.message_id)

async def handle_callbacks(call):
    if call.data == "force_scan":
        await bot.answer_callback_query(call.id, "🔍 Сканирую новости...")
        posts = await generate_posts_pack("")
        if posts:
            for post in posts:
                await send_crafted_post(call.message.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
        else:
            await bot.send_message(call.message.chat.id, "Новостей нет")
    
    elif call.data == "calendar":
        cal = await get_f1_calendar(14)
        await bot.send_message(call.message.chat.id, cal, parse_mode="HTML")
        await bot.answer_callback_query(call.id)
    
    elif call.data == "chat_mode":
        STATE["chat_mode"] = not STATE["chat_mode"]
        mode = "включён" if STATE["chat_mode"] else "выключен"
        await bot.send_message(call.message.chat.id, f"💬 Режим диалога {mode}")
        await bot.answer_callback_query(call.id)
    
    elif call.data == "auto_post":
        await bot.answer_callback_query(call.id, "📰 Генерирую пост...")
        posts = await generate_posts_pack("Сделай аналитический пост о последних событиях в F1")
        for post in posts:
            await send_crafted_post(call.message.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
    
    elif call.data == "pub_direct_action":
        try:
            if call.message.caption:
                await bot.send_photo("@RedRaceF1", call.message.photo[-1].file_id, caption=call.message.caption, parse_mode="HTML")
            else:
                await bot.send_message("@RedRaceF1", call.message.text, parse_mode="HTML")
            await bot.answer_callback_query(call.id, "Опубликовано в канал!")
            await bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception as e:
            print(f"Publish error: {e}")
        return
    
    await bot.answer_callback_query(call.id)

async def auto_post_worker():
    while True:
        await asyncio.sleep(STATE['auto_interval'])
        if STATE.get("kill_switch") or STATE['chat_mode']:
            continue
        try:
            posts = await generate_posts_pack("")
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
    bot_instance.register_message_handler(admin_panel, commands=['admin', 'start'])
    bot_instance.register_message_handler(manual_trigger, func=lambda m: True, content_types=['text'])
    bot_instance.register_callback_query_handler(handle_callbacks, func=lambda call: True)

async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    register_handlers(bot)
    asyncio.create_task(auto_post_worker())
    asyncio.create_task(polling_worker())
    print("🚀 Nico PRO started on Render!")
    print("💬 Чат-бот активен. Пиши любые вопросы про F1!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
