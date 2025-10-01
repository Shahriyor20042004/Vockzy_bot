# main.py (исправленный)
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, PollAnswer, BotCommandScopeAllPrivateChats, BotCommand
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import Command, CommandStart
from sql import init_db, get_words_for_user, add_word, delete_all_words
from config import API_TOKEN
import random
import logging
import asyncio
import fitz
import re
import json, urllib.parse
from aiogram import types

# Более подробное логирование для отладки
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

# НЕ вызывать include_router здесь — сначала объявляем все хэндлеры, потом подключаем роутер

active_tests = {}
current_polls = {}
pending_answers = {}

stop_test_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⛔️ Остановить тест", callback_data="stop_test")]]
)

# ---------------- handlers ----------------

@router.message(CommandStart())
async def start_command(message: Message):
    await message.answer(
        "Привет! Я ваш бот для изучения слов.\n"
        "Мои команды:\n"
        "- /add — добавить слова \n"
        "- Образец: слово - перевод,  ...\n"
        "- Можете отправить текстовый файл (txt),(pdf) для загрузки слов\n"
        "- /list — чтобы узнать список слов\n"
        "- /delete_all — удалить все слова\n"
        "- /test — начать тестирование\n"
        "- /swap_test — начать тестирование наоборот\n"
        "- /manual_test — ручной тест\n"
        "- /game — запустить мини-игру с вашими словами"
    )

@router.message(Command("add"))
async def add_command(message: Message):
    user_id = message.from_user.id
    try:
        _, words_text = message.text.split(maxsplit=1)
        word_pairs = [pair.strip().split('-', maxsplit=1) for pair in words_text.split(",")]
        added_words = []
        for pair in word_pairs:
            if len(pair) == 2:
                phrase, translation = pair
                phrase = phrase.strip()
                translation = translation.strip()
                if phrase and translation:
                    await add_word(phrase, translation, user_id)
                    added_words.append(f"{phrase} — {translation}")
            else:
                await message.answer(f"Ошибка в формате пары: {pair}. Используйте формат: словосочетание - перевод.")
        if added_words:
            await message.answer(f"Добавлены слова и словосочетания:\n" + "\n".join(added_words))
    except ValueError:
        await message.answer("Используйте формат: /add словосочетание1 - перевод1, ...")
    except Exception as e:
        logger.exception("Ошибка при add_command: %s", e)
        await message.answer("Произошла ошибка при добавлении слов.")

@router.message(lambda message: message.document and message.document.file_name.lower().endswith(('.txt', '.pdf')))
async def handle_file(message: Message):
    user_id = message.from_user.id
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    file_content = await bot.download_file(file_path)

    try:
        if message.document.file_name.lower().endswith('.txt'):
            content = file_content.read().decode('utf-8')
        elif message.document.file_name.lower().endswith('.pdf'):
            with open("temp.pdf", "wb") as f:
                f.write(file_content.read())
            doc = fitz.open("temp.pdf")
            content = ""
            for page in doc:
                content += page.get_text()
            doc.close()
        else:
            await message.answer("❌ Поддерживаются только .txt и .pdf файлы.")
            return

        lines = content.splitlines()
        added_words = []

        for line in lines:
            parts = re.split(r'\s*[-–—]\s*', line, maxsplit=1)
            if len(parts) == 2:
                phrase = parts[0].strip()
                translation = parts[1].strip()
                if phrase and translation:
                    await add_word(phrase, translation, user_id)
                    added_words.append(f"{phrase} - {translation}")

        if added_words:
            await message.answer(f"✅ Добавлены слова:\n" + "\n".join(added_words))
        else:
            await message.answer("❌ Файл не содержит строк в формате: <слово> - <перевод>")
    except Exception as e:
        logger.exception("Ошибка обработки файла: %s", e)
        await message.answer("⚠️ Ошибка при разборе файла. Проверьте формат.")

@router.message(Command("list"))
async def list_words(message: Message):
    user_id = message.from_user.id
    try:
        words = await get_words_for_user(user_id)
        if not words:
            await message.answer("Ваш список слов пока пуст. Вы можете добавить новые слова с помощью команды /add.")
            return
        word_list = "\n".join([f"{word} — {translation}" for word, translation in words])
        for chunk in chunk_list(word_list.splitlines(), 50):
            await message.answer("\n".join(chunk))
    except Exception as e:
        logger.exception("Ошибка при получении списка слов: %s", e)
        await message.answer("Произошла ошибка при получении списка слов.")
        
@router.message(Command("delete_all"))
async def delete_all_command(message: Message):
    user_id = message.from_user.id
    try:
        await delete_all_words(user_id)
        await message.answer("Все добавленные слова были успешно удалены!")
    except Exception as e:
        logger.exception("Ошибка при удалении всех слов: %s", e)
        await message.answer("Произошла ошибка при удалении слов.")

def chunk_list(lst, chunk_size):
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]


# ---------- GAME handler ----------
GITHUB_GAME_URL = "https://shahriyor20042004.github.io/Game/"

@router.message(Command("game"))
async def send_game(message: types.Message):
    logger.info("Received /game from user_id=%s", message.from_user.id)
    try:
        user_id = message.from_user.id

        # Получаем слова из БД
        words = await get_words_for_user(user_id)
        if not words:
            await message.answer("У тебя пока нет слов. Добавь их командой /add.")
            return

        # Ограничим количество слов
        MAX_WORDS_IN_URL = 100
        words = words[:MAX_WORDS_IN_URL]

        words_list = [[w[0], w[1]] for w in words]
        words_json = json.dumps(words_list, ensure_ascii=False)
        words_param = urllib.parse.quote(words_json)
        url = f"{GITHUB_GAME_URL}?words={words_param}"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Играть", web_app=WebAppInfo(url=url))]
            ]
        )

        await message.answer("Запускай игру 👇", reply_markup=keyboard)
        logger.info("Sent WebApp button for user_id=%s (words=%d)", user_id, len(words_list))

    except Exception as e:
        logger.exception("Error in /game handler for user_id=%s: %s", message.from_user.id, e)
        await message.answer("Произошла ошибка при подготовке игры. Попробуйте позже.")

# ---- тесты (как у тебя были) ----

@router.message(Command("test"))
async def start_test(message: Message):
    user_id = message.from_user.id

    if user_id in active_tests:
        await message.answer("Тест уже запущен!", reply_markup=stop_test_keyboard)
        return

    active_tests[user_id] = True
    await message.answer("Тест начат! Новый вопрос отправится после вашего ответа.", reply_markup=stop_test_keyboard)
    await send_next_quiz(user_id)

async def send_next_quiz(chat_id):
    if chat_id not in active_tests:
        return
    words = await get_words_for_user(chat_id)
    if not words:
        await bot.send_message(chat_id, "Список слов пуст. Добавьте слова через /add.")
        del active_tests[chat_id]
        return
    phrase, correct_answer = random.choice(words)
    all_translations = [w[1] for w in words if w[1] != correct_answer]
    wrong_answers = random.sample(all_translations, min(3, len(all_translations)))
    options = [correct_answer] + wrong_answers
    random.shuffle(options)
    poll = await bot.send_poll(
        chat_id=chat_id,
        question=f"Как переводится '{phrase}'?",
        options=options,
        type="quiz",
        correct_option_id=options.index(correct_answer),
        is_anonymous=False,
        reply_markup=stop_test_keyboard
    )
    current_polls[chat_id] = poll.poll.id

@router.message(Command("swap_test"))
async def reverse_test(message: Message):
    user_id = message.from_user.id

    if user_id in active_tests:
        await message.answer("Тест уже запущен!", reply_markup=stop_test_keyboard)
        return

    active_tests[user_id] = True
    await message.answer("Тест начат! Новый вопрос отправится после вашего ответа.", reply_markup=stop_test_keyboard)
    await send_next_reverse_quiz(user_id)

async def send_next_reverse_quiz(chat_id):
    if chat_id not in active_tests:
        return
    words = await get_words_for_user(chat_id)
    if not words:
        await bot.send_message(chat_id, "Список слов пуст. Добавьте слова через /add.")
        del active_tests[chat_id]
        return
    correct_answer, word = random.choice(words)
    all_words = [w[0] for w in words if w[0] != correct_answer]
    wrong_answers = random.sample(all_words, min(3, len(all_words)))
    options = [correct_answer] + wrong_answers
    random.shuffle(options)
    poll = await bot.send_poll(
        chat_id=chat_id,
        question=f"Как переводится '{word}'?",
        options=options,
        type="quiz",
        correct_option_id=options.index(correct_answer),
        is_anonymous=False,
        reply_markup=stop_test_keyboard
    )
    current_polls[chat_id] = poll.poll.id

@router.message(Command("manual_test"))
async def manual_test(message: Message):
    user_id = message.from_user.id

    if user_id in active_tests:
        await message.answer("Тест уже запущен! Используйте /stop_test для остановки.", reply_markup=stop_test_keyboard)
        return

    words = await get_words_for_user(user_id)
    if not words:
        await message.answer("Список слов пуст. Добавьте слова через /add.")
        return

    active_tests[user_id] = 'manual'
    await send_manual_question(user_id)

async def send_manual_question(user_id: int):
    if user_id not in active_tests or active_tests[user_id] != 'manual':
        return

    words = await get_words_for_user(user_id)
    if not words:
        await bot.send_message(user_id, "Список слов пуст. Добавьте слова через /add.")
        del active_tests[user_id]
        return

    word = random.choice(words)
    original, translation = word
    pending_answers[user_id] = (original, translation)
    await bot.send_message(user_id, f"Как переводится: **{original}**?", parse_mode="Markdown", reply_markup=stop_test_keyboard)

@router.message()
async def handle_user_translation(message: Message):
    user_id = message.from_user.id
    if user_id not in active_tests or active_tests[user_id] != 'manual':
        return

    user_input = message.text.strip().lower()
    _, correct_translation = pending_answers[user_id]
    valid_answers = [t.strip().lower() for t in correct_translation.split(',')]

    if user_input in valid_answers:
        await message.answer("✅ Правильно!", reply_markup=stop_test_keyboard)
    else:
        await message.answer(f"❌ Неправильно. Правильный перевод: {correct_translation}", reply_markup=stop_test_keyboard)

    await send_manual_question(user_id)

@router.poll_answer()
async def poll_answer_handler(poll_answer: PollAnswer):
    user_id = poll_answer.user.id
    if user_id in active_tests:
        if user_id in current_polls and poll_answer.poll_id == current_polls[user_id]:
            await send_next_quiz(user_id)
        else:
            await send_next_reverse_quiz(user_id)



@router.message(Command("stop_test"))
async def stop_test(message: Message):
    user_id = message.from_user.id
    if user_id in active_tests:
        del active_tests[user_id]
        current_polls.pop(user_id, None)
        pending_answers.pop(user_id, None)
        await state.clear()
        await message.answer("Тест остановлен.")
    else:
        await message.answer("Тест не был запущен.")

@router.callback_query(lambda c: c.data == "stop_test")
async def stop_test_button(callback_query):
    user_id = callback_query.from_user.id
    if user_id in active_tests:
        del active_tests[user_id]
        current_polls.pop(user_id, None)
        pending_answers.pop(user_id, None)
        await callback_query.message.answer("Тест остановлен.")
        await callback_query.answer()



# ------ Тестовый минимальный handler для проверки регистрации (временно/удалить later) -----
@router.message(Command("game_test"))
async def game_test(message: Message):
    logger.info("game_test called for %s", message.from_user.id)
    await message.answer("handler /game_test работает")

# ---------------- include router (ВАЖНО: делать после определения всех handler'ов) ------------
dp.include_router(router)

# ---------------- commands list и запуск ----------------
private = [
    BotCommand(command='start', description='начальная команда'),
    BotCommand(command='test', description='Начать обычный тест'),
    BotCommand(command='swap_test', description='Начать обратный тест'),
    BotCommand(command='manual_test', description='Начать ручной тест'),
    BotCommand(command='delete_all', description='Удаление всех слов'),
    BotCommand(command='list', description='Для просмотра списока слов'),
    BotCommand(command='game', description='Запустить мини-игру')
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
