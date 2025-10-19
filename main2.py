# main.py (исправленный с распознаванием дефисов и тире)
from aiogram import Bot, Dispatcher, Router
from aiogram.types import (
    Message, PollAnswer, BotCommandScopeAllPrivateChats,
    BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)
from aiogram.filters import Command, CommandStart
from sql import init_db, get_words_for_user, add_word, delete_all_words
from config import API_TOKEN
import random
import logging
import asyncio
import fitz
import re
import json
import urllib.parse
from aiogram import types

# ---------------- Логирование ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

active_tests = {}
current_polls = {}
pending_answers = {}

stop_test_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⛔️ Остановить тест", callback_data="stop_test")]]
)

# ---------------- Команда /start ----------------
@router.message(CommandStart())
async def start_command(message: Message):
    await message.answer(
        "👋 Привет! Я бот для изучения слов.\n\n"
        "📘 Команды:\n"
        "- /add — добавить слова (пример: work - работа, mother-in-law - тёща)\n"
        "- можно отправить файл .txt или .pdf с парами слов\n"
        "- /list — список слов\n"
        "- /delete_all — удалить все слова\n"
        "- /test — тест (слово → перевод)\n"
        "- /swap_test — обратный тест (перевод → слово)\n"
        "- /manual_test — ручной тест\n"
        "- /game — мини-игра 🎮"
    )

# ---------------- Добавление слов ----------------
@router.message(Command("add"))
async def add_command(message: Message):
    user_id = message.from_user.id
    try:
        _, words_text = message.text.split(maxsplit=1)

        # Разделяем пары по запятым, но не ломаем дефисные слова
        pairs = re.split(r',(?![^()]*\))', words_text)

        added_words = []
        for pair in pairs:
            pair = pair.strip()
            if not pair:
                continue

            # 🧠 Разделяем только по тире, не по дефису внутри слова
            parts = re.split(r'\s*[-–—]\s*', pair, maxsplit=1)

            if len(parts) == 2:
                phrase, translation = parts
                phrase = phrase.strip()
                translation = translation.strip()
                if phrase and translation:
                    await add_word(phrase, translation, user_id)
                    added_words.append(f"{phrase} — {translation}")

        if added_words:
            await message.answer("✅ Добавлены слова:\n" + "\n".join(added_words))
        else:
            await message.answer("❌ Не найдено строк формата: слово - перевод.\n\n"
                                 "ℹ️ Пример: `book - книга`, `mother-in-law - тёща`")

    except Exception as e:
        logger.exception("Ошибка при добавлении слов: %s", e)
        await message.answer("⚠️ Произошла ошибка при добавлении слов.")

# ---------------- Загрузка файлов ----------------
@router.message(lambda message: message.document and message.document.file_name.lower().endswith(('.txt', '.pdf')))
async def handle_file(message: Message):
    user_id = message.from_user.id
    file = await bot.get_file(message.document.file_id)
    file_path = file.file_path
    file_content = await bot.download_file(file_path)

    try:
        if message.document.file_name.lower().endswith('.txt'):
            content = file_content.read().decode('utf-8', errors='ignore')
        else:
            with open("temp.pdf", "wb") as f:
                f.write(file_content.read())
            doc = fitz.open("temp.pdf")
            content = "".join(page.get_text() for page in doc)
            doc.close()

        added_words = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue

            # 🧠 Основная логика: ищем тире, но не дефис
            parts = re.split(r'\s*[-–—]\s*', line, maxsplit=1)

            if len(parts) == 2:
                phrase, translation = parts
                phrase = phrase.strip()
                translation = translation.strip()
                if phrase and translation:
                    await add_word(phrase, translation, user_id)
                    added_words.append(f"{phrase} — {translation}")

        if added_words:
            await message.answer("✅ Добавлены слова:\n" + "\n".join(added_words[:50]))
        else:
            await message.answer("❌ Не найдено строк формата: слово - перевод.\n"
                                 "Проверь, чтобы тире было между словом и переводом, а не дефисом в слове.")

    except Exception as e:
        logger.exception("Ошибка обработки файла: %s", e)
        await message.answer("⚠️ Ошибка при обработке файла. Проверь формат.")

# ---------------- Список слов ----------------
@router.message(Command("list"))
async def list_words(message: Message):
    user_id = message.from_user.id
    words = await get_words_for_user(user_id)
    if not words:
        await message.answer("📭 Список слов пуст. Добавь их через /add.")
        return
    text = "\n".join([f"{w} — {t}" for w, t in words])
    for chunk in chunk_list(text.splitlines(), 50):
        await message.answer("\n".join(chunk))

def chunk_list(lst, chunk_size):
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]

# ---------------- Удаление слов ----------------
@router.message(Command("delete_all"))
async def delete_all_command(message: Message):
    user_id = message.from_user.id
    await delete_all_words(user_id)
    await message.answer("🗑 Все слова удалены!")

# ---------------- GAME ----------------
GITHUB_GAME_URL = "https://shahriyor20042004.github.io/Game/"

@router.message(Command("game"))
async def send_game(message: types.Message):
    user_id = message.from_user.id
    words = await get_words_for_user(user_id)

    if not words:
        await message.answer("❌ У тебя пока нет слов. Добавь их командой /add.")
        return

    # ✅ Берем случайные 30 слов, даже если у пользователя 500+
    MAX_WORDS = 30
    selected_words = random.sample(words, min(MAX_WORDS, len(words)))

    words_json = json.dumps(selected_words, ensure_ascii=False)
    words_param = urllib.parse.quote(words_json)
    url = f"{GITHUB_GAME_URL}?words={words_param}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🎮 Играть", web_app=WebAppInfo(url=url))]]
    )

    await message.answer(
        f"🚀 Запускай игру!\n📚 Используются {len(selected_words)} случайных слов из твоей базы.",
        reply_markup=keyboard
    )

# ---------------- Тесты ----------------
async def send_next_quiz(user_id):
    words = await get_words_for_user(user_id)
    if not words:
        await bot.send_message(user_id, "Список слов пуст. Добавь слова через /add.")
        active_tests.pop(user_id, None)
        return
    phrase, correct = random.choice(words)
    options = [correct] + random.sample([w[1] for w in words if w[1] != correct], min(3, len(words)-1))
    random.shuffle(options)
    poll = await bot.send_poll(
        chat_id=user_id,
        question=f"Как переводится '{phrase}'?",
        options=options,
        type="quiz",
        correct_option_id=options.index(correct),
        is_anonymous=False,
        reply_markup=stop_test_keyboard
    )
    current_polls[user_id] = ("test", poll.poll.id)

@router.message(Command("test"))
async def start_test(message: Message):
    user_id = message.from_user.id
    if user_id in active_tests:
        await message.answer("Тест уже идёт!", reply_markup=stop_test_keyboard)
        return
    active_tests[user_id] = "test"
    await message.answer("🧠 Тест начат!", reply_markup=stop_test_keyboard)
    await send_next_quiz(user_id)

# ---- Обратный тест ----
async def send_next_swap_quiz(user_id):
    words = await get_words_for_user(user_id)
    if not words:
        await bot.send_message(user_id, "Список слов пуст. Добавь слова через /add.")
        active_tests.pop(user_id, None)
        return
    correct, question = random.choice(words)
    options = [correct] + random.sample([w[0] for w in words if w[0] != correct], min(3, len(words)-1))
    random.shuffle(options)
    poll = await bot.send_poll(
        chat_id=user_id,
        question=f"Что означает '{question}'?",
        options=options,
        type="quiz",
        correct_option_id=options.index(correct),
        is_anonymous=False,
        reply_markup=stop_test_keyboard
    )
    current_polls[user_id] = ("swap", poll.poll.id)

@router.message(Command("swap_test"))
async def swap_test(message: Message):
    user_id = message.from_user.id
    if user_id in active_tests:
        await message.answer("Тест уже идёт!", reply_markup=stop_test_keyboard)
        return
    active_tests[user_id] = "swap"
    await message.answer("🔄 Обратный тест начат!", reply_markup=stop_test_keyboard)
    await send_next_swap_quiz(user_id)

# ---- Ручной тест ----
@router.message(Command("manual_test"))
async def manual_test(message: Message):
    user_id = message.from_user.id
    if user_id in active_tests:
        await message.answer("Тест уже идёт!", reply_markup=stop_test_keyboard)
        return
    active_tests[user_id] = "manual"
    await send_manual_question(user_id)

async def send_manual_question(user_id):
    words = await get_words_for_user(user_id)
    if not words:
        await bot.send_message(user_id, "Список слов пуст.")
        active_tests.pop(user_id, None)
        return
    word, translation = random.choice(words)
    pending_answers[user_id] = translation.lower()
    await bot.send_message(user_id, f"✍️ Переведи: **{word}**", parse_mode="Markdown", reply_markup=stop_test_keyboard)

@router.message()
async def handle_manual_answer(message: Message):
    user_id = message.from_user.id
    if user_id not in active_tests or active_tests[user_id] != "manual":
        return
    correct = pending_answers.get(user_id, "")
    if message.text.strip().lower() == correct:
        await message.answer("✅ Правильно!", reply_markup=stop_test_keyboard)
    else:
        await message.answer(f"❌ Неправильно. Правильный ответ: {correct}", reply_markup=stop_test_keyboard)
    await send_manual_question(user_id)

# ---- Ответы в опросах ----
@router.poll_answer()
async def poll_answer_handler(poll_answer: PollAnswer):
    user_id = poll_answer.user.id
    if user_id not in current_polls:
        return
    mode, _ = current_polls[user_id]
    if mode == "test":
        await send_next_quiz(user_id)
    elif mode == "swap":
        await send_next_swap_quiz(user_id)

# ---- Остановка тестов ----
@router.message(Command("stop_test"))
async def stop_test(message: Message):
    user_id = message.from_user.id
    for d in (active_tests, current_polls, pending_answers):
        d.pop(user_id, None)
    await message.answer("⛔️ Тест остановлен.")

@router.callback_query(lambda c: c.data == "stop_test")
async def stop_test_button(callback_query):
    user_id = callback_query.from_user.id
    for d in (active_tests, current_polls, pending_answers):
        d.pop(user_id, None)
    await callback_query.message.answer("⛔️ Тест остановлен.")
    await callback_query.answer()

# ---------------- Запуск ----------------
dp.include_router(router)

private = [
    BotCommand(command='start', description='начальная команда'),
    BotCommand(command='add', description='добавить слова'),
    BotCommand(command='list', description='показать список слов'),
    BotCommand(command='delete_all', description='удалить все слова'),
    BotCommand(command='test', description='начать тест'),
    BotCommand(command='swap_test', description='обратный тест'),
    BotCommand(command='manual_test', description='ручной тест'),
    BotCommand(command='game', description='запустить мини-игру')
]

async def init_and_start():
    await init_db()
    await bot.set_my_commands(commands=private, scope=BotCommandScopeAllPrivateChats())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(init_and_start())
    except KeyboardInterrupt:
        print("Бот выключен")
