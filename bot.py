import os
import asyncio
from datetime import timedelta, time

# --- Разрешаем unsafe-доступ к Django ORM (только для локального бота!) ---
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

import django
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from django.conf import settings
from django.utils import timezone
from dotenv import load_dotenv
from gtts import gTTS

# --- Установка event loop для Windows ---
try:
    from asyncio import WindowsSelectorEventLoopPolicy
    asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
except Exception:
    pass

# --- Настройка Django ---
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# --- Загрузка токена ---
load_dotenv()
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не найден в .env")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Импорт моделей после django.setup() ---
from django.contrib.auth.models import User
from cards.models import Card, Schedule, UserStats


# --- Клавиатура ---
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/today"), KeyboardButton(text="/test")],
            [KeyboardButton(text="/match"), KeyboardButton(text="/review")],
            [KeyboardButton(text="/progress"), KeyboardButton(text="/cards")],
            [KeyboardButton(text="/help")]
        ],
        resize_keyboard=True
    )


# --- /start — с автоматическим /help ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    try:
        user_stats = UserStats.objects.get(telegram_id=user_id)
        await message.answer("С возвращением! Я тебя помню 😊", reply_markup=get_main_keyboard())
        await cmd_help(message)
    except UserStats.DoesNotExist:
        try:
            user = User.objects.first()
            if not user:
                await message.answer("Ошибка: нет пользователей в системе.")
                return

            user_stats, created = UserStats.objects.get_or_create(
                user=user,
                defaults={'telegram_id': user_id}
            )
            if not created:
                user_stats.telegram_id = user_id
                user_stats.save()

            await message.answer(
                f"Привет, {message.from_user.first_name}! 👋\n"
                "Я связал тебя с твоим аккаунтом в LinguaTrack.\n"
                "Теперь ты можешь учить слова в боте!",
                reply_markup=get_main_keyboard()
            )
            await cmd_help(message)
        except Exception as e:
            await message.answer("Ошибка подключения к базе.")
            print(e)


# --- /help ---
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📚 Доступные команды:\n"
        "  /today — слова на сегодня\n"
        "  /test — пройти тест\n"
        "  /match — игра \"Сопоставление\"\n"
        "  /review — повторить слова\n"
        "  /progress — мой прогресс\n"
        "  /cards — мои карточки\n"
        "  /add — добавить карточку\n"
        "  /edit — изменить карточку\n"
        "  /delete — удалить карточку\n"
        "  /say <слово> — озвучить слово\n"
        "  /set_reminder — установить время напоминаний\n"
        "  /help — эта подсказка"
    )


# --- /today — слова на повторении ---
@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    user_id = message.from_user.id
    try:
        user_stats = UserStats.objects.select_related('user').get(telegram_id=user_id)
        user = user_stats.user

        due_cards = list(
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
    except Exception as e:
        await message.answer("Ошибка при загрузке слов.")
        print(f"Ошибка /today: {e}")


# --- /progress — статистика ---
@dp.message(Command("progress"))
async def cmd_progress(message: types.Message):
    user_id = message.from_user.id
    try:
        user_stats = UserStats.objects.select_related('user').get(telegram_id=user_id)
        user = user_stats.user

        total = Card.objects.filter(owner=user).count()
        learned = Card.objects.filter(owner=user, schedule__repetitions__gte=3).count()

        await message.answer(
            f"📊 Твой прогресс:\n"
            f"Всего карточек: {total}\n"
            f"Выучено слов: {learned}\n"
            f"Серия повторений: {user_stats.review_streak}"
        )
    except Exception as e:
        await message.answer("Ошибка при загрузке статистики.")
        print(f"Ошибка /progress: {e}")


# --- /cards — список карточек ---
@dp.message(Command("cards"))
async def cmd_cards(message: types.Message):
    user_id = message.from_user.id
    try:
        user_stats = UserStats.objects.select_related('user').get(telegram_id=user_id)
        user = user_stats.user

        cards = list(Card.objects.filter(owner=user)[:10])

        if cards:
            response = "Твои карточки (первые 10):\n\n"
            for card in cards:
                response += f"• *{card.word}* → {card.translation}\n"
            await message.answer(response, parse_mode="Markdown")
        else:
            await message.answer("У тебя пока нет карточек.")
    except Exception as e:
        await message.answer("Ошибка при загрузке карточек.")
        print(f"Ошибка /cards: {e}")


# --- /say — озвучка слова ---
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
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


# --- Редактор карточек ---
@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    await message.answer("Отправь: `слово | перевод | пример | примечание | уровень`")
    if not hasattr(bot, 'waiting_for'):
        bot.waiting_for = {}
    bot.waiting_for[message.from_user.id] = 'add_card'


@dp.message(Command("edit"))
async def cmd_edit(message: types.Message):
    await message.answer("Напиши слово, которое хочешь изменить.")
    if not hasattr(bot, 'waiting_for'):
        bot.waiting_for = {}
    bot.waiting_for[message.from_user.id] = 'edit_word'


@dp.message(Command("delete"))
async def cmd_delete(message: types.Message):
    await message.answer("Напиши слово, которое хочешь удалить.")
    if not hasattr(bot, 'waiting_for'):
        bot.waiting_for = {}
    bot.waiting_for[message.from_user.id] = 'delete_word'


# --- /test — тест с карточками ---
@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    user_id = message.from_user.id
    try:
        user_stats = UserStats.objects.get(telegram_id=user_id)
        user = user_stats.user

        cards = list(Card.objects.filter(owner=user))
        if len(cards) < 4:
            await message.answer("Нужно хотя бы 4 слова.")
            return

        import random
        random.shuffle(cards)
        card = cards[0]
        options = [card.translation] + [c.translation for c in random.sample(cards[1:], 3)]
        random.shuffle(options)

        if not hasattr(bot, 'test_data'):
            bot.test_data = {}
        bot.test_data[user_id] = card.translation

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=opt)] for opt in options],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await message.answer(
            f"🎯 Тест: что означает *{card.word}*?",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer("Ошибка при запуске теста.")
        print(f"Ошибка /test: {e}")


# --- Ответ на тест ---
@dp.message(lambda m: hasattr(bot, 'test_data') and m.from_user.id in bot.test_data)
async def handle_test_answer(message: types.Message):
    user_id = message.from_user.id
    correct = bot.test_data[user_id]

    if message.text == correct:
        await message.answer("✅ Правильно!", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Правильно: *{correct}*", parse_mode="Markdown", reply_markup=get_main_keyboard())

    del bot.test_data[user_id]


# --- /match — игра ---
@dp.message(Command("match"))
async def cmd_match(message: types.Message):
    user_id = message.from_user.id
    try:
        user_stats = UserStats.objects.get(telegram_id=user_id)
        user = user_stats.user

        cards = list(Card.objects.filter(owner=user))
        if len(cards) < 2:
            await message.answer("Нужно хотя бы 2 слова.")
            return

        import random
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
            keyboard=[[KeyboardButton(text=f"{words[0]} → {opt}")] for opt in options],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await message.answer(
            f"🧠 Сопоставь: *{words[0]}*",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer("Ошибка при запуске игры.")
        print(f"Ошибка /match: {e}")


# --- Ответ на игру ---
@dp.message(lambda m: '→' in m.text and m.text.count('→') == 1)
async def handle_match_answer(message: types.Message):
    user_id = message.from_user.id
    if not hasattr(bot, 'match_data') or user_id not in bot.match_data:
        return

    try:
        word, given = [part.strip() for part in message.text.split('→')]
    except:
        return

    correct = bot.match_data[user_id].get(word)
    if not correct:
        await message.answer("Ошибка проверки.")
        return

    result = "✅ Правильно!" if given == correct else f"❌ Правильно: *{correct}*"
    await message.answer(result, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    del bot.match_data[user_id]


# --- /review — повторение ---
@dp.message(Command("review"))
async def cmd_review(message: types.Message):
    user_id = message.from_user.id
    try:
        user_stats = UserStats.objects.get(telegram_id=user_id)
        user = user_stats.user

        due_cards = list(
            Card.objects.filter(
                owner=user,
                schedule__next_review__lte=timezone.now()
            )
        )

        if not due_cards:
            await message.answer("🎉 Сегодня нет слов для повторения!")
            return

        card = due_cards[0]
        if not hasattr(bot, 'review_data'):
            bot.review_data = {}
        bot.review_data[user_id] = {'card_id': card.id, 'word': card.word}

        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🔴 Забыл")],
                [KeyboardButton(text="🟡 Сложно")],
                [KeyboardButton(text="🟢 Легко")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await message.answer(
            f"🔁 Повторение:\n\n**{card.word}**?",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer("Ошибка при загрузке слов.")
        print(f"Ошибка /review: {e}")


# --- Обработка ответа на повторение ---
@dp.message(lambda m: m.text in ["🔴 Забыл", "🟡 Сложно", "🟢 Легко"])
async def handle_review_answer(message: types.Message):
    user_id = message.from_user.id
    if not hasattr(bot, 'review_data') or user_id not in bot.review_data:
        return

    data = bot.review_data[user_id]
    try:
        card = Card.objects.get(id=data['card_id'])
        schedule = card.schedule

        difficulty = 'hard' if message.text == "🔴 Забыл" \
            else 'good' if message.text == "🟡 Сложно" else 'easy'

        # Прямо вызываем — без sync_to_async
        schedule.update_schedule(difficulty)
        schedule.save()

        user_stats = UserStats.objects.get(telegram_id=user_id)
        user_stats.review_streak += 1
        user_stats.last_reviewed = timezone.now()
        user_stats.save()

        del bot.review_data[user_id]
        await message.answer("✅ Готово!", reply_markup=get_main_keyboard())
    except Exception as e:
        await message.answer("Ошибка при обработке ответа.")
        print(f"Ошибка в handle_review_answer: {e}")


# --- /set_reminder — установка времени напоминаний ---
@dp.message(Command("set_reminder"))
async def cmd_set_reminder(message: types.Message):
    await message.answer("Напиши время в формате `ЧЧ:ММ` (например, `09:00`).")
    if not hasattr(bot, 'waiting_for'):
        bot.waiting_for = {}
    bot.waiting_for[message.from_user.id] = 'set_reminder_time'


# --- Обработка времени ---
@dp.message()
async def handle_reminder_time(message: types.Message):
    if not hasattr(bot, 'waiting_for') or message.from_user.id not in bot.waiting_for:
        return

    if bot.waiting_for[message.from_user.id] != 'set_reminder_time':
        return

    try:
        time_str = message.text.strip()
        hours, minutes = map(int, time_str.split(':'))
        reminder_time = time(hour=hours, minute=minutes)

        user_stats = UserStats.objects.get(telegram_id=message.from_user.id)
        user_stats.reminder_time = reminder_time
        user_stats.save()

        await message.answer(f"✅ Напоминания установлены на {time_str}.")
        del bot.waiting_for[message.from_user.id]
    except Exception:
        await message.answer("Неверный формат. Используй `ЧЧ:ММ`.")


# --- Логирование активных пользователей ---
@dp.message()
async def log_user(message: types.Message):
    if not hasattr(bot, 'active_users'):
        bot.active_users = set()
    bot.active_users.add(message.from_user.id)


# --- Напоминания ---
async def send_local_reminders():
    if not hasattr(bot, 'active_users') or not bot.active_users:
        return

    now = timezone.now().time()
    for user_id in list(bot.active_users):
        try:
            user_stats = UserStats.objects.get(telegram_id=user_id)
            if user_stats.reminder_time:
                if (user_stats.reminder_time.hour == now.hour and
                        abs(user_stats.reminder_time.minute - now.minute) < 2):
                    await bot.send_message(
                        chat_id=user_id,
                        text="🔔 *Напоминание!* ⏰\n"
                             "Не забудь повторить слова сегодня!\n\n"
                             "📌 /today — начать повторение",
                        parse_mode="Markdown"
                    )
        except Exception as e:
            print(f"❌ Не удалось отправить напоминание {user_id}: {e}")


# --- Запуск бота ---
async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_local_reminders, 'interval', minutes=1)
    scheduler.start()
    print("🚀 Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())