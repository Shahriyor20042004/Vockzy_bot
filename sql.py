import aiosqlite

# Подключение к базе данных
DATABASE = 'words.db'

# Инициализация базы данных
async def init_db():
    """
    Инициализирует таблицу words в базе данных.
    """
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                translation TEXT NOT NULL,
                UNIQUE(user_id, word)  -- Ограничение уникальности только на user_id и слово
            )
        ''')
        await db.commit()

# Добавление слова в базу данных
async def add_word(word: str, translation: str, user_id: int):
    """
    Добавляет слово и перевод для конкретного пользователя.
    Если слово уже существует, возбуждается исключение.
    """
    try:
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute(
                "INSERT INTO words (user_id, word, translation) VALUES (?, ?, ?)",
                (user_id, word, translation)
            )
            await db.commit()
    except aiosqlite.IntegrityError:
        raise ValueError(f"Слово '{word}' уже существует для пользователя {user_id}!")

# Удаление конкретного слова
async def delete_word(word: str, user_id: int):
    """
    Удаляет указанное слово для конкретного пользователя.
    """
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("DELETE FROM words WHERE word = ? AND user_id = ?", (word, user_id))
        await db.commit()

# Удаление всех слов пользователя
async def delete_all_words(user_id: int):
    """
    Удаляет все слова, добавленные конкретным пользователем.
    """
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("DELETE FROM words WHERE user_id = ?", (user_id,))
        await db.commit()

# Получение всех слов для пользователя
async def get_words_for_user(user_id: int):
    """
    Получает список всех слов и переводов для конкретного пользователя.
    """
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT word, translation FROM words WHERE user_id = ?", (user_id,))
        words = await cursor.fetchall()
        return words