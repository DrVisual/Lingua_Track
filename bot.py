import os
import asyncio
import re
from datetime import time, timedelta

import django
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from django.utils.timezone import localtime
from dotenv import load_dotenv
from gtts import gTTS
import random

# Настройка Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# Загрузка переменных окружения
load_dotenv()

# Проверка токена
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("Токен Telegram не найден в .env")

# Создание бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Импорт моделей (после django.setup())
from django.contrib.auth.models import User
from cards.models import Card, Schedule, UserStats


# --- КЛАВИАТУРА ---
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/today"), KeyboardButton(text="/test")],
            [KeyboardButton(text="/progress"), KeyboardButton(text="/cards")],
            [KeyboardButton(text="/help")]
        ],
        resize_keyboard=True
    )


# --- ОСНОВНЫЕ КОММАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id

    try:
        user_stats = await sync_to_async(UserStats.objects.get)(telegram_id=user_id)
        await message.answer("С возвращением! Я тебя помню 😊")
    except UserStats.DoesNotExist:
        try:
            user = await sync_to_async(User.objects.first)()
            if not user:
                await message.answer("Ошибка: нет пользователей в системе.")
                return

            user_stats, created = await sync_to_async(UserStats.objects.get_or_create)(
                user=user,
                defaults={'telegram_id': user_id}
            )
            if not created:
                user_stats.telegram_id = user_id
                await sync_to_async(user_stats.save)()

            await message.answer(
                f"Привет, {message.from_user.first_name}! 👋\n"
                "Я связал тебя с твоим аккаунтом в LinguaTrack.\n"
                "Теперь ты можешь учить слова в боте!"
            )
        except Exception as e:
            await message.answer("Ошибка подключения к базе. Попробуй позже.")
            print(e)

    await message.answer(
        "Готов помочь! Используй команды ниже:",
        reply_markup=get_main_keyboard()
    )


@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    user_id = message.from_user.id

    try:
        user_stats = await sync_to_async(
            UserStats.objects.select_related('user').get
        )(telegram_id=user_id)
        user = user_stats.user

        due_cards = await sync_to_async(list)(
            Card.objects.filter(
                owner=user,
                schedule__next_review__lte=timezone.now()
            )
        )

        if due_cards:
            response = "Слова на сегодня:\n\n"
            for card in due_cards:
                response += f"📌 *{card.word}* → {card.translation}\n"
            await message.answer(response, parse_mode="Markdown")
        else:
            await message.answer("🎉 Сегодня нет слов для повторения!")
    except UserStats.DoesNotExist:
        await message.answer("Ты не привязан к аккаунту. Напиши /start")


@dp.message(Command("progress"))
async def cmd_progress(message: types.Message):
    user_id = message.from_user.id

    try:
        user_stats = await sync_to_async(
            UserStats.objects.select_related('user').get
        )(telegram_id=user_id)
        user = user_stats.user

        total = await sync_to_async(Card.objects.filter(owner=user).count)()
        learned = await sync_to_async(
            Card.objects.filter(owner=user, schedule__repetitions__gte=3).count
        )()

        await message.answer(
            f"📊 Твой прогресс:\n"
            f"Всего карточек: {total}\n"
            f"Выучено слов: {learned}\n"
            f"Серия повторений: {user_stats.review_streak}\n"
            f"Последнее повторение: {user_stats.last_reviewed.strftime('%d.%m.%Y') if user_stats.last_reviewed else '—'}"
        )
    except UserStats.DoesNotExist:
        await message.answer("Ты не привязан к аккаунту. Напиши /start")


@dp.message(Command("cards"))
async def cmd_cards(message: types.Message):
    user_id = message.from_user.id

    try:
        user_stats = await sync_to_async(
            UserStats.objects.select_related('user').get
        )(telegram_id=user_id)
        user = user_stats.user

        cards = await sync_to_async(list)(Card.objects.filter(owner=user)[:10])

        if cards:
            response = "Твои карточки (первые 10):\n\n"
            for card in cards:
                response += f"• *{card.word}* → {card.translation}\n"
            await message.answer(response, parse_mode="Markdown")
        else:
            await message.answer("У тебя пока нет карточек. Добавь в веб-версии!")
    except UserStats.DoesNotExist:
        await message.answer("Ты не привязан к аккаунту. Напиши /start")


@dp.message(Command("say"))
async def cmd_say(message: types.Message):
    text = message.text.split(' ', 1)
    if len(text) < 2:
        await message.answer("Напиши слово после команды. Пример: /say hello")
        return

    word = text[1].strip()
    if not word:
        await message.answer("Слово не может быть пустым.")
        return

    os.makedirs("temp", exist_ok=True)
    audio_path = f"temp/{word}.mp3"

    try:
        tts = gTTS(text=word, lang='en')
        tts.save(audio_path)
        voice = FSInputFile(audio_path)
        await message.answer_voice(voice, caption=f"🔊 *{word}*", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"Не удалось озвучить слово: {e}")
        print(e)
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


# --- ТЕСТ С ВЫБОРОМ ---

@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    user_id = message.from_user.id
    try:
        # Получаем пользователя
        user_stats = await sync_to_async(UserStats.objects.get)(telegram_id=user_id)
        user = user_stats.user

        # Получаем карточки
        cards = await sync_to_async(list)(Card.objects.filter(owner=user))
        if len(cards) < 4:
            await message.answer("Нужно хотя бы 4 слова, чтобы пройти тест.")
            return

        # Перемешиваем
        random.shuffle(cards)
        card = cards[0]
        options = [card.translation] + [c.translation for c in cards[1:4]]
        random.shuffle(options)

        # Сохраняем правильный ответ
        if not hasattr(bot, 'test_data'):
            bot.test_data = {}
        bot.test_data[user_id] = card.translation

        # Клавиатура
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=options[0])],
                [KeyboardButton(text=options[1])],
                [KeyboardButton(text=options[2])],
                [KeyboardButton(text=options[3])],
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await message.answer(
            f"🎯 Тест: что означает слово *{card.word}*?",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer("Ошибка при запуске теста.")
        print(e)


@dp.message(lambda m: hasattr(bot, 'test_data') and m.from_user.id in bot.test_data)
async def handle_test_answer(message: types.Message):
    user_id = message.from_user.id
    correct = bot.test_data[user_id]

    if message.text == correct:
        await message.answer("✅ Правильно! Молодец!", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Неверно. Правильный ответ: *{correct}*", parse_mode="Markdown", reply_markup=get_main_keyboard())

    del bot.test_data[user_id]


# --- СОПОСТАВЛЕНИЕ СЛОВ И ПЕРЕВОДОВ ---

@dp.message(Command("match"))
async def cmd_match(message: types.Message):
    user_id = message.from_user.id
    try:
        user_stats = await sync_to_async(UserStats.objects.get)(telegram_id=user_id)
        user = user_stats.user

        cards = await sync_to_async(list)(Card.objects.filter(owner=user))
        if len(cards) < 2:
            await message.answer("Нужно хотя бы 2 слова, чтобы сыграть.")
            return

        random.shuffle(cards)
        sample = cards[:4]

        words = [c.word for c in sample]
        translations = [c.translation for c in sample]
        random.shuffle(translations)

        if not hasattr(bot, 'match_data'):
            bot.match_data = {}
        bot.match_data[user_id] = {c.word: c.translation for c in sample}

        options = translations[:]
        random.shuffle(options)

        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=f"{words[0]} → {options[0]}")],
                [KeyboardButton(text=f"{words[0]} → {options[1]}")],
                [KeyboardButton(text=f"{words[0]} → {options[2]}")],
                [KeyboardButton(text=f"{words[0]} → {options[3]}")],
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await message.answer(
            f"🧠 Сопоставь слово с переводом:\n\n"
            f"Слово: *{words[0]}*\n"
            f"Выбери правильный перевод:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer("Ошибка при запуске игры.")
        print(e)


@dp.message(lambda m: '→' in m.text and m.text.count('→') == 1)
async def handle_match_answer(message: types.Message):
    user_id = message.from_user.id
    if not hasattr(bot, 'match_data') or user_id not in bot.match_data:
        return

    try:
        word, given_translation = [part.strip() for part in message.text.split('→')]
    except:
        return

    correct_translation = bot.match_data[user_id].get(word)
    if not correct_translation:
        await message.answer("Не удалось проверить ответ.")
        return

    if given_translation == correct_translation:
        result = "✅ Правильно!"
    else:
        result = f"❌ Неверно. Правильно: *{correct_translation}*"

    await message.answer(result, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    del bot.match_data[user_id]


# --- НАПОМИНАНИЯ ---

@dp.message(Command("remind_at"))
async def cmd_remind_at(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    match = re.search(r'(\d{1,2})[:\s](\d{2})', text)
    if not match:
        await message.answer(
            "Укажи время в формате ЧЧ:ММ. Например:\n"
            "  /remind_at 20:30\n"
            "  /remind_at 9:00"
        )
        return

    try:
        hour = int(match.group(1))
        minute = int(match.group(2))

        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            await message.answer("Время некорректно. Укажи от 00:00 до 23:59.")
            return

        user_time = time(hour=hour, minute=minute)

        try:
            user_stats = await sync_to_async(UserStats.objects.get)(telegram_id=user_id)
            user_stats.reminder_time = user_time
            await sync_to_async(user_stats.save)()

            await message.answer(
                f"✅ Время напоминания установлено: {user_time.strftime('%H:%M')}\n"
                "Теперь каждый день в это время я буду напоминать повторять слова!"
            )
        except UserStats.DoesNotExist:
            await message.answer("Сначала напиши /start")
    except Exception as e:
        await message.answer("Не удалось установить время. Попробуй снова.")
        print(e)


async def send_daily_reminders():
    """Отправляет напоминания в индивидуальное время"""
    try:
        now = timezone.now()
        local_now = localtime(now)
        current_time = time(local_now.hour, local_now.minute)

        user_stats_list = await sync_to_async(list)(
            UserStats.objects.select_related('user')
            .exclude(telegram_id__isnull=True)
            .filter(reminder_time=current_time)
        )

        for user_stats in user_stats_list:
            user = user_stats.user
            due_count = await sync_to_async(
                Card.objects.filter(
                    owner=user,
                    schedule__next_review__lte=now
                ).count
            )()

            if due_count > 0:
                try:
                    await bot.send_message(
                        chat_id=user_stats.telegram_id,
                        text=(
                            f"🔔 Напоминание!\n"
                            f"У тебя **{due_count} слов(а)** на повторение.\n"
                            f"Не забудь повторить — иначе прогресс сбросится!\n\n"
                            f"👉 /today — начать повторение"
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"❌ Ошибка отправки {user_stats.telegram_id}: {e}")

    except Exception as e:
        print(f"🚨 Ошибка в send_daily_reminders: {e}")


# --- ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ ---

@dp.message(Command("reschedule"))
async def cmd_reschedule(message: types.Message):
    text = message.text.split()
    if len(text) < 3:
        await message.answer("Используй: /reschedule <слово> через <N> дней")
        return

    word = text[1]
    try:
        days = int(text[3])
    except (ValueError, IndexError):
        await message.answer("Укажи число дней после 'через'")
        return

    user_id = message.from_user.id
    try:
        user_stats = await sync_to_async(UserStats.objects.get)(telegram_id=user_id)
        user = user_stats.user
        card = await sync_to_async(Card.objects.get)(owner=user, word__iexact=word)
        schedule = card.schedule
        schedule.next_review = timezone.now() + timedelta(days=days)
        await sync_to_async(schedule.save)()
        await message.answer(f"✅ Слово *{word}* перенесено на повторение через {days} дней.", parse_mode="Markdown")
    except Card.DoesNotExist:
        await message.answer("Слово не найдено.")
    except Exception as e:
        await message.answer("Ошибка при переносе.")
        print(e)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📚 Доступные команды:\n"
        "  /start — начать\n"
        "  /today — слова на сегодня\n"
        "  /test — пройти тест\n"
        "  /match — сопоставление слов\n"
        "  /progress — мой прогресс\n"
        "  /say <слово> — озвучить\n"
        "  /cards — список карточек\n"
        "  /remind_at ЧЧ:ММ — установить напоминание\n"
        "  /reschedule <слово> через N дней — перенести повторение\n"
        "  /help — эта подсказка"
    )


@dp.message(Command("debug_time"))
async def cmd_debug_time(message: types.Message):
    now = timezone.now()
    local_now = localtime(now)
    await message.answer(
        f"🌍 UTC: {now.strftime('%H:%M:%S')}\n"
        f"⏰ Local: {local_now.strftime('%H:%M:%S')}\n"
        f"⚙️ TIME_ZONE: {settings.TIME_ZONE}"
    )


@dp.message(Command("debug_user"))
async def cmd_debug_user(message: types.Message):
    user_id = message.from_user.id
    try:
        user_stats = await sync_to_async(UserStats.objects.get)(telegram_id=user_id)
        reminder_time = user_stats.reminder_time
        now = timezone.now()
        local_now = localtime(now)
        current_time = time(local_now.hour, local_now.minute)

        await message.answer(
            f"📱 Твой Telegram ID: {user_id}\n"
            f"🔔 Время напоминания: {reminder_time}\n"
            f"🕒 Текущее локальное время: {current_time}\n"
            f"📅 Совпадает? {reminder_time == current_time}"
        )
    except UserStats.DoesNotExist:
        await message.answer("Не найден в базе. Напиши /start")


# --- ЗАПУСК БОТА ---

async def main():
    print("🚀 Бот и планировщик запущены")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_reminders, 'cron', minute='*')  # каждую минуту
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())