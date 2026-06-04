import asyncio
import os
import time
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineQueryResultPhoto
from aiohttp import web

from scraper import (
    monitor, post_on_topic, random_post, get_calendar, chat_reply,
    morning_digest, get_pending_posts, clear_pending_posts,
    get_driver_standings, get_last_race_results, get_next_race,
    analyze_photo, search_brave_images, fast_standings_reply, fast_last_race_reply,
    get_random_character
)
from database import (
    init_db, save_conversation, get_stats, get_all_users,
    get_last_dialogs, clear_all_history, get_user_message_count,
    save_bug_report
)

# === КОНФИГ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
BETA_USERS = {7076945880: "sunrise"}

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальные состояния
monitoring = True
posts_cnt = 0
dialogs_cnt = 0
start_time = time.time()
wait_topic = {}
wait_broadcast = {}
wait_post = {}
wait_bug = {}
waiting_photo = {}

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def is_admin(user_id): return user_id in ADMIN_IDS
def is_beta(user_id): return user_id in BETA_USERS
def inc_posts(): global posts_cnt; posts_cnt += 1
def inc_dialogs(): global dialogs_cnt; dialogs_cnt += 1

# === КЛАВИАТУРЫ ===
def get_admin_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton(text="📝 Пост на тему"), KeyboardButton(text="🎲 Рандом"),
        KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📜 История"),
        KeyboardButton(text="👥 Пользователи"), KeyboardButton(text="📨 Рассылка"),
        KeyboardButton(text="📤 Пост в канал"), KeyboardButton(text="🎭 Персонаж"),
        KeyboardButton(text="🛑 Стоп"), KeyboardButton(text="▶️ Старт"),
        KeyboardButton(text="📰 Новости"), KeyboardButton(text="✅ Опубликовать"),
        KeyboardButton(text="🧠 Очистить"), KeyboardButton(text="🔬 Анализ фото"),
        KeyboardButton(text="📅 Календарь"), KeyboardButton(text="🏆 Чемпионат"),
        KeyboardButton(text="🏁 Последняя гонка"), KeyboardButton(text="⏩ Следующая гонка")
    )
    return markup

def get_beta_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton(text="📝 Пост на тему"), KeyboardButton(text="🎲 Рандом"),
        KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🎭 Персонаж"),
        KeyboardButton(text="🐞 Баг"), KeyboardButton(text="👤 Профиль"),
        KeyboardButton(text="🔬 Отладка"), KeyboardButton(text="📈 Телеметрия"),
        KeyboardButton(text="📅 Календарь"), KeyboardButton(text="🏆 Чемпионат"),
        KeyboardButton(text="🏁 Последняя гонка")
    )
    return markup

def get_user_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton(text="📅 Календарь"),
        KeyboardButton(text="🏆 Чемпионат"),
        KeyboardButton(text="🏁 Последняя гонка"),
        KeyboardButton(text="🎭 Персонаж"),
        KeyboardButton(text="🔬 Анализ фото")
    )
    return markup

# === КОМАНДЫ ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    if is_admin(user_id):
        uptime = time.time() - start_time
        status = f"👑 Нико онлайн\nАптайм: {int(uptime//3600)}ч\nМониторинг: {'✅' if monitoring else '⛔'}\nПостов: {posts_cnt}\nНовостей: {len(get_pending_posts())}"
        await message.answer(status, parse_mode="HTML", reply_markup=get_admin_keyboard())
    elif is_beta(user_id):
        stats = get_stats()
        msgs = get_user_message_count(user_id)
        status = f"🤖 Привет, бета-тестер\nПостов: {stats['posts']}\nТвоих сообщений: {msgs}"
        await message.answer(status, parse_mode="HTML", reply_markup=get_beta_keyboard())
    else:
        status = """🏎️ **Я Нико 3.0 — твой гоночный инженер.**

• Отвечаю на вопросы про F1
• Анализирую фото болидов
• Знаю таблицу чемпионата
• Показываю результаты гонок

🎮 **Карточная игра:** @sipmly_flag_bot"""
        await message.answer(status, parse_mode="HTML", reply_markup=get_user_keyboard())

@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message):
    user_id = message.from_user.id
    wait_topic[user_id] = False
    wait_broadcast[user_id] = False
    wait_post[user_id] = False
    wait_bug[user_id] = False
    waiting_photo[user_id] = False
    await message.answer("❌ Действие отменено")

# === F1 КНОПКИ ===
@dp.message(lambda m: m.text == "🏆 Чемпионат")
async def show_standings(message: types.Message):
    await message.answer(await fast_standings_reply(), parse_mode="HTML")

@dp.message(lambda m: m.text == "🏁 Последняя гонка")
async def show_last_race(message: types.Message):
    await message.answer(await fast_last_race_reply(), parse_mode="HTML")

@dp.message(lambda m: m.text == "⏩ Следующая гонка")
async def show_next_race(message: types.Message):
    race = await get_next_race(2026)
    if not race:
        await message.answer("❌ Данные следующей гонки недоступны")
        return
    text = f"⏩ **Следующая гонка**\n\n🏎️ {race['name']}\n📅 {race['date']}\n🏁 {race['circuit']}"
    await message.answer(text, parse_mode="HTML")

@dp.message(lambda m: m.text == "📅 Календарь")
async def show_calendar(message: types.Message):
    await message.answer(await get_calendar(), parse_mode="HTML")

@dp.message(lambda m: m.text == "🎭 Персонаж")
async def show_character(message: types.Message):
    await message.answer(get_random_character(), parse_mode="HTML")

# === ОБРАБОТЧИК ФОТО ===
@dp.message(lambda m: m.photo)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    if waiting_photo.get(user_id, False):
        waiting_photo[user_id] = False
        file_id = message.photo[-1].file_id
        file = await bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        status = await message.answer("🔍 Анализирую...")
        analysis = await analyze_photo(file_url)
        await status.edit_text(analysis, parse_mode="HTML")

# === ОСНОВНОЙ ОБРАБОТЧИК ТЕКСТА ===
@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    # Guest Mode
    if hasattr(message, 'guest_query_id') and message.guest_query_id:
        answer = await chat_reply(user_id, text)
        answer += "\n\n🏎️ Red Race | Подписаться"
        await bot.answer_guest_query(
            guest_query_id=message.guest_query_id,
            text=answer,
            parse_mode="HTML"
        )
        return
    
    # Ожидания
    if wait_bug.get(user_id, False):
        wait_bug[user_id] = False
        save_bug_report(user_id, text)
        await message.answer("✅ Баг отправлен админу")
        for admin_id in ADMIN_IDS:
            await bot.send_message(admin_id, f"🐞 Баг от {user_id}:\n{text}")
        return
    
    if wait_broadcast.get(user_id, False):
        wait_broadcast[user_id] = False
        users = get_all_users()
        sent = 0
        for uid, _, _, _, _ in users:
            try:
                await bot.send_message(int(uid), f"📢 {text}", parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)
            except:
                pass
        await message.answer(f"✅ Отправлено {sent}")
        return
    
    if wait_topic.get(user_id, False):
        wait_topic[user_id] = False
        status = await message.answer("📝 Генерирую...")
        post = await post_on_topic(text)
        await status.delete()
        await message.answer(post, parse_mode="HTML")
        inc_posts()
        return
    
    if waiting_photo.get(user_id, False):
        waiting_photo[user_id] = False
        await message.answer("📸 Отправь фото")
        return
    
    # Админ кнопки
    if is_admin(user_id):
        if text == "📝 Пост на тему":
            wait_topic[user_id] = True
            await message.answer("📝 Тема:")
        elif text == "🎲 Рандом":
            await message.answer(await random_post(), parse_mode="HTML")
            inc_posts()
        elif text == "📊 Статистика":
            stats = get_stats()
            uptime = time.time() - start_time
            await message.answer(f"📊 Постов: {stats['posts']}\n💬 Диалогов: {stats['dialogs']}\n👥 Пользователей: {stats['users']}\n🐞 Багов: {stats['bugs']}\n⏱ Аптайм: {int(uptime//3600)}ч\n📡 Мониторинг: {'✅' if monitoring else '⛔'}", parse_mode="HTML")
        elif text == "📜 История":
            rows = get_last_dialogs(20)
            if not rows:
                await message.answer("📭 Пусто")
            else:
                resp = "📜 Последние диалоги:\n\n"
                for uid, msg, ans, ts in rows[:10]:
                    resp += f"👤 {uid} | {ts[:16]}\n❓ {msg[:50]}\n✅ {ans[:50]}\n\n---\n"
                await message.answer(resp[:4000], parse_mode="HTML")
        elif text == "👥 Пользователи":
            users = get_all_users(30)
            if not users:
                await message.answer("📭 Нет пользователей")
            else:
                resp = "👥 Пользователи:\n"
                for uid, username, first_name, msgs, _ in users:
                    name = first_name or username or uid[:10]
                    resp += f"• {name} — {msgs} сообщений\n"
                await message.answer(resp[:4000])
        elif text == "📨 Рассылка":
            wait_broadcast[user_id] = True
            await message.answer("📨 Введите текст рассылки:")
        elif text == "📤 Пост в канал":
            wait_post[user_id] = True
            await message.answer("📤 Отправьте контент в канал (30 сек):")
            asyncio.create_task(reset_post_timeout(user_id))
        elif text == "🛑 Стоп":
            monitoring = False
            await message.answer("⛔ Мониторинг остановлен")
        elif text == "▶️ Старт":
            monitoring = True
            await message.answer("✅ Мониторинг запущен")
        elif text == "📰 Новости":
            posts = get_pending_posts()
            if not posts:
                await message.answer("📭 Новостей нет")
            else:
                resp = f"📰 Готово ({len(posts)}):\n"
                for i, p in enumerate(posts[:10], 1):
                    resp += f"{i}. {p['title'][:60]}\n"
                await message.answer(resp)
        elif text == "✅ Опубликовать":
            posts = get_pending_posts()
            if not posts:
                await message.answer("📭 Нет новостей")
            else:
                await message.answer(f"📤 Публикую {len(posts)}...")
                for p in posts:
                    await bot.send_message(CHANNEL_ID, p['post'], parse_mode="HTML")
                    inc_posts()
                    await asyncio.sleep(2)
                clear_pending_posts()
                await message.answer(f"✅ Опубликовано {len(posts)}")
        elif text == "🧠 Очистить":
            clear_all_history()
            await message.answer("🧠 История очищена")
        elif text == "🔬 Анализ фото":
            waiting_photo[user_id] = True
            await message.answer("📸 Отправь фото болида или трассы")
        else:
            status = await message.answer("🤔 Думаю...")
            answer = await chat_reply(user_id, text)
            await status.delete()
            await message.answer(answer, parse_mode="HTML")
            inc_dialogs()
            save_conversation(str(user_id), text, answer, username=message.from_user.username, first_name=message.from_user.first_name)
        return
    
    # Бета кнопки
    if is_beta(user_id):
        if text == "🐞 Баг":
            wait_bug[user_id] = True
            await message.answer("🐞 Опиши баг:")
        elif text == "👤 Профиль":
            msgs = get_user_message_count(user_id)
            await message.answer(f"👤 Сообщений: {msgs}\nРоль: Бета", parse_mode="HTML")
        elif text == "🔬 Отладка":
            uptime = time.time() - start_time
            await message.answer(f"🔬 Отладка\nМониторинг: {'✅' if monitoring else '❌'}\nАптайм: {int(uptime//3600)}ч\nПостов: {posts_cnt}", parse_mode="HTML")
        elif text == "📈 Телеметрия":
            stats = get_stats()
            await message.answer(f"📈 Постов: {stats['posts']}\nДиалогов: {stats['dialogs']}\nПользователей: {stats['users']}", parse_mode="HTML")
        elif text in ["📝 Пост на тему", "🎲 Рандом", "📊 Статистика", "📅 Календарь", "🏆 Чемпионат", "🏁 Последняя гонка", "🎭 Персонаж", "🔬 Анализ фото"]:
            if text == "📝 Пост на тему":
                wait_topic[user_id] = True
                await message.answer("📝 Тема:")
            elif text == "🎲 Рандом":
                await message.answer(await random_post(), parse_mode="HTML")
                inc_posts()
            elif text == "📊 Статистика":
                stats = get_stats()
                await message.answer(f"📊 Постов: {stats['posts']}\nДиалогов: {stats['dialogs']}\nПользователей: {stats['users']}", parse_mode="HTML")
            elif text == "📅 Календарь":
                await message.answer(await get_calendar(), parse_mode="HTML")
            elif text == "🏆 Чемпионат":
                await message.answer(await fast_standings_reply(), parse_mode="HTML")
            elif text == "🏁 Последняя гонка":
                await message.answer(await fast_last_race_reply(), parse_mode="HTML")
            elif text == "🎭 Персонаж":
                await message.answer(get_random_character(), parse_mode="HTML")
            elif text == "🔬 Анализ фото":
                waiting_photo[user_id] = True
                await message.answer("📸 Отправь фото болида или трассы")
        else:
            status = await message.answer("🤔 Думаю...")
            answer = await chat_reply(user_id, text)
            await status.delete()
            await message.answer(answer, parse_mode="HTML")
            inc_dialogs()
            save_conversation(str(user_id), text, answer, username=message.from_user.username, first_name=message.from_user.first_name)
        return
    
    # Пользовательские кнопки
    if text in ["📅 Календарь", "🏆 Чемпионат", "🏁 Последняя гонка", "🎭 Персонаж", "🔬 Анализ фото"]:
        if text == "📅 Календарь":
            await message.answer(await get_calendar(), parse_mode="HTML")
        elif text == "🏆 Чемпионат":
            await message.answer(await fast_standings_reply(), parse_mode="HTML")
        elif text == "🏁 Последняя гонка":
            await message.answer(await fast_last_race_reply(), parse_mode="HTML")
        elif text == "🎭 Персонаж":
            await message.answer(get_random_character(), parse_mode="HTML")
        elif text == "🔬 Анализ фото":
            waiting_photo[user_id] = True
            await message.answer("📸 Отправь фото болида или трассы")
        return
    
    # Обычный чат
    status = await message.answer("🤔 Думаю...")
    answer = await chat_reply(user_id, text)
    await status.delete()
    await message.answer(answer, parse_mode="HTML")
    inc_dialogs()
    save_conversation(str(user_id), text, answer, username=message.from_user.username, first_name=message.from_user.first_name)

# === INLINE MODE ===
@dp.inline_query()
async def inline_search(inline_query: types.InlineQuery):
    query_text = inline_query.query.strip()
    if not query_text:
        await inline_query.answer([], switch_pm_text="🔍 Напиши что найти", switch_pm_parameter="start")
        return
    
    standings = await get_driver_standings(2026)
    results = []
    
    if standings:
        for s in standings:
            if query_text.lower() in s['driver'].lower():
                results.append(
                    InlineQueryResultPhoto(
                        id=f"driver_{s['pos']}",
                        photo_url="https://cdn-8.motorsport.com/images/mgl/6Qv0KXj0/s1000/ferrari-sf-25-1-.jpg",
                        thumbnail_url="https://cdn-8.motorsport.com/images/mgl/6Qv0KXj0/s100/ferrari-sf-25-1-.jpg",
                        title=s['driver'],
                        description=f"{s['points']} очков, {s['team']}",
                        caption=f"🏎️ {s['driver']} — {s['points']} очков\n{s['team']}\n#F1"
                    )
                )
    
    if not results and BRAVE_KEY:
        images = await search_brave_images(query_text, max_results=10)
        for img in images:
            results.append(
                InlineQueryResultPhoto(
                    id=img['id'],
                    photo_url=img['url'],
                    thumbnail_url=img['thumbnail'],
                    title=img['title'][:60],
                    caption=f"🖼️ {img['title'][:100]}\n#Search"
                )
            )
    
    if results:
        await inline_query.answer(results[:20], cache_time=300, is_personal=True)
    else:
        await inline_query.answer([], cache_time=60)

# === ТАЙМАУТ ===
async def reset_post_timeout(user_id):
    await asyncio.sleep(30)
    wait_post[user_id] = False

# === HEALTHCHECK ===
async def start_health_server():
    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="Nico is alive"))
    app.router.add_get("/health", lambda request: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Health check on port {port}")

# === УТРЕННИЙ ДАЙДЖЕСТ ===
async def morning_digest_worker():
    while True:
        now = datetime.now()
        target = now.replace(hour=4, minute=0, second=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            digest = await morning_digest()
            await bot.send_message(CHANNEL_ID, digest, parse_mode="HTML")
            print("☀️ Дайджест отправлен")
        except Exception as e:
            print(f"Digest error: {e}")

# === ЗАПУСК ===
async def main():
    init_db()
    await start_health_server()
    asyncio.create_task(monitor())
    asyncio.create_task(morning_digest_worker())
    print("🚀 NICO 3.0 ЗАПУЩЕН")
    print(f"👑 Админ: {ADMIN_IDS}")
    print(f"🔧 Бета: {list(BETA_USERS.keys())}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
