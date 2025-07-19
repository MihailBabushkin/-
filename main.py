import random
import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command 
from aiogram.filters.state import StateFilter  
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatType
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from typing import Callable, Awaitable, Dict, Any
from aiogram.types import ReplyKeyboardRemove
from PIL import Image, ImageDraw, ImageFont
import os
from aiogram.types import Message
from datetime import datetime, timedelta

last_used = {} #словарь последнего вызова пользователем (см в показ паспорта)

# Генератор 12-значного номера счета
def generate_account_number():
    return str(random.randint(10**11, 10**12 - 1))  # Генерирует число от 100000000000 до 999999999999


# Настройки
BOT_TOKEN = "7989088801:AAEviiVC1DQ8XFFNNcrMozFAMENEdavyiGw"
ADMIN_ID = 6313754974

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Middleware-фильтр, разрешающий команды только в ЛС (кроме /deportation)
class PrivateCommandMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: Callable[[types.Message, Dict[str, Any]], Awaitable[Any]],
            event: types.Message,
            data: Dict[str, Any]
    ) -> Any:
        if event.text and (event.text.startswith("/deportation") or
                           event.text.startswith("/clear_buttons") or
                           event.text.startswith("/my_passport")):
            return await handler(event, data)
        if event.chat.type != ChatType.PRIVATE and event.text and event.text.startswith("/"):
            return  # игнорируем команду вне ЛС
        return await handler(event, data)

# Регистрация middleware
dp.message.middleware(PrivateCommandMiddleware())

#FSM классы
class Marriage(StatesGroup):
    enter_spouse_account = State()

class Settings(StatesGroup):
    waiting_for_new_name = State()

class Broadcast(StatesGroup):
    waiting_for_message = State()
    confirm = State()

class SetBalance(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_balance = State()

class Register(StatesGroup):
    name = State()
    gender = State()
    city = State()

class Transfer(StatesGroup):
    enter_recipient = State()
    enter_amount = State()
    confirm = State()

class Divorce(StatesGroup):
    confirm = State()

class ChangeCity(StatesGroup):
    choose_city = State()
    enter_custom_city = State()

class Appointment(StatesGroup):
    choose_doctor = State()
    choose_time = State()

class Statement(StatesGroup):
    enter_text = State()

# Инициализация БД
async def init_db():
    async with aiosqlite.connect("database.db") as db:
        # Создаем таблицу users
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    account_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    gender TEXT NOT NULL,
    city TEXT NOT NULL,
    balance INTEGER DEFAULT 1,
    spouse_id TEXT,
    registration_date DATETIME DEFAULT CURRENT_TIMESTAMP)
        """)

        # Создаем таблицу transfers
        await db.execute("""
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user TEXT NOT NULL,           -- Отправитель (номер счета)
            to_user TEXT NOT NULL,             -- Получатель (номер счета)
            amount INTEGER NOT NULL,           -- Сумма перевода
            commission INTEGER DEFAULT 0,      -- Комиссия
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP -- Время перевода
        )
        """)

        # Создаем таблицу statements
        await db.execute("""
        CREATE TABLE IF NOT EXISTS statements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,          -- ID пользователя
            text TEXT NOT NULL,                -- Текст заявления
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP -- Время подачи
        )
        """)

        # Создаем таблицу appointments
        await db.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,          -- ID пользователя
            doctor TEXT NOT NULL,              -- Врач
            time TEXT NOT NULL,                -- Время приема
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP -- Время записи
        )
        """)

        # Создаем таблицу broadcasts
        await db.execute("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,        -- ID администратора
            message TEXT NOT NULL,             -- Текст рассылки
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, -- Время рассылки
            success_count INTEGER DEFAULT 0,   -- Успешные отправки
            fail_count INTEGER DEFAULT 0       -- Неудачные отправки
        )
        """)

        await db.commit()

# Клавиатуры
def main_menu_kb(spouse_exists: bool):
    buttons = [
        [KeyboardButton(text="💰 Новый перевод")],
        [KeyboardButton(text="🧑‍⚕ Записаться ко врачу")],
        [KeyboardButton(text="📝 Написать заявление")],
        [KeyboardButton(text="📂 Истории")],
        [KeyboardButton(text="✏️ Изменить имя")],
    ]
    if spouse_exists:
        buttons.append([KeyboardButton(text="💔 Развестись")])
    else:
        buttons.append([KeyboardButton(text="💍 Зарегистрировать брак")])
    buttons.append([KeyboardButton(text="🏠 Изменить место жительства")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


# Клавиатура меню истории
def history_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📜 История переводов")],
            [KeyboardButton(text="📄 История заявлений")],
            [KeyboardButton(text="🧑‍⚕ История записей ко врачу")],
            [KeyboardButton(text="↩ Назад")],
        ],
        resize_keyboard=True
    )


def confirm_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Подтвердить"), KeyboardButton(text="Отмена")],
        ], resize_keyboard=True
    )

def doctors_kb():
    buttons = [
        [KeyboardButton(text="(уборщик) Кандидат инцельских наук и инцелофильствоведства Родион Сергеевич Пидорасович")],
        [KeyboardButton(text="(зубной) Иванов Иван Иванович")],
        [KeyboardButton(text="(Венеролог) Лобанов Илья Питрюхонович")],
        [KeyboardButton(text="(Офтальмолог) Вагинов Андрей Михайлович")],
        [KeyboardButton(text="(Уролог) Пистрохуньев Евгений Артёмович")],
        [KeyboardButton(text="(Гинекологичка) Шлюхова Наталья Ивановна")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def times_kb():
    buttons = [
        [KeyboardButton(text="10:00")],
        [KeyboardButton(text="10:30")],
        [KeyboardButton(text="11:00")],
        [KeyboardButton(text="11:30")],
        [KeyboardButton(text="12:00")],
        [KeyboardButton(text="12:30")],
        [KeyboardButton(text="13:00")],
        [KeyboardButton(text="13:30")],
        [KeyboardButton(text="15:00")],
        [KeyboardButton(text="15:30")],
        [KeyboardButton(text="16:00")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

# Клавиатура с городами
def cities_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='ФГР. Шуя')],
            [KeyboardButton(text='ФГР. Шуйская Петронезия')],
            [KeyboardButton(text='Нижний Блаж')],
            [KeyboardButton(text='ФГР. Аркхем')],
            [KeyboardButton(text='ФГР. Сабрие')],
            [KeyboardButton(text='ФГР. Лост-Парадайз')],
            [KeyboardButton(text='Болвания')]
        ],
        resize_keyboard=True
    )
# Функция показа главного меню
async def show_full_profile_menu(message: types.Message, user_id: int):
    """Показывает полную информацию о профиле с заданным форматированием"""
    async with aiosqlite.connect("database.db") as db:
        # Получаем все данные пользователя за один запрос
        cursor = await db.execute("""
            SELECT 
                name, gender, city, balance, id as account_id,
                spouse_id, (SELECT name FROM users WHERE id = u.spouse_id) as spouse_name
            FROM users u
            WHERE user_id = ?
        """, (user_id,))
        user_data = await cursor.fetchone()

    if not user_data:
        await message.answer("❌ Профиль не найден. Завершите регистрацию")
        return

    name, gender, city, balance, account_id, spouse_id, spouse_name = user_data

    # Форматируем сообщение строго по требованиям
    profile_message = (
        f"📕 <b>Паспорт {name}</b>\n\n"
        f"💛├ 🆔 <b>Гос ID:</b> <code>{account_id}</code>\n"
        f"💛├ 👤 <b>Имя:</b> <code>{name}</code>\n"
        f"🤍├ 👫 <b>Пол:</b> <code>{'Мужской' if gender == 'м' else 'Женский'}</code>\n"
        f"🤍├ 💍 <b>Супруг(а):</b> <code>{spouse_name if spouse_name else 'Нет'}</code>\n"
        f"💙├ 🏙 <b>Город:</b> <code>{city}</code>\n"
        f"💙└ 💳 <b>Баланс:</b> <code>{balance}</code> шуек\n"
    )

    # Отправляем сообщение с HTML-разметкой
    await message.answer(profile_message, parse_mode="HTML")

    # Показываем основное меню
    await message.answer("Выберите действие:", reply_markup=main_menu_kb(spouse_exists=bool(spouse_id)))

# Команда /clear_buttons (работает только не в ЛС)
@dp.message(Command("clear_buttons"))
async def clear_buttons_handler(message: types.Message):
    if message.chat.type != ChatType.PRIVATE:
        await message.answer(
            "Клавиатура убрана.",
            reply_markup=ReplyKeyboardRemove()        )
    else:
        await message.answer("Команда /clear_buttons работает только вне ЛС.")


# Проверка уникальности номера счета
async def is_account_unique(account_number: str, db: aiosqlite.Connection) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM users WHERE account_id = ? LIMIT 1",
        (account_number,)
    )
    return await cursor.fetchone() is None

# Генерация уникального номера счета
async def generate_account_number(db: aiosqlite.Connection) -> str:
    while True:
        account_number = str(random.randint(10**11, 10**12 - 1))
        if await is_account_unique(account_number, db):
            return account_number

#старт
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    try:
        async with aiosqlite.connect("database.db") as db:
            cursor = await db.execute(
                "SELECT 1 FROM users WHERE user_id = ?",
                (user_id,)
            )
            is_registered = await cursor.fetchone()

        if is_registered:
            await show_full_profile_menu(message, user_id)
        else:
            await message.answer("Привет! Для регистрации введите ваше имя:")
            await state.set_state(Register.name)

    except Exception as e:
        await message.answer("⚠️ Произошла ошибка. Попробуйте позже.")
        print(f"Ошибка при проверке регистрации: {e}")

# Обработчик ввода имени
@dp.message(Register.name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 50:
        await message.answer("Пожалуйста, введите имя (макс. 50 символов)")
        return

    await state.update_data(name=name)
    await message.answer("Укажите ваш пол (м/ж):")
    await state.set_state(Register.gender)


# Обработчик ввода пола
@dp.message(Register.gender)
async def process_gender(message: types.Message, state: FSMContext):
    gender = message.text.strip().lower()
    if gender not in ['м', 'ж']:
        await message.answer("Пожалуйста, укажите 'м' или 'ж'")
        return

    await state.update_data(gender=gender)
    await message.answer("Выберите ваш город:", reply_markup=cities_kb())
    await state.set_state(Register.city)


# Обработчик выбора города и завершение регистрации
@dp.message(Register.city)
async def process_city(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    city = message.text.strip()
    valid_cities = [
        'ФГР. Шуя', 'ФГР. Шуйская Петронезия', 'Нижний Блаж',
        'ФГР. Аркхем', 'ФГР. Сабрие', 'ФГР. Лост-Парадайз', 'Болвания'
    ]

    if city not in valid_cities:
        await message.answer("Пожалуйста, выберите город из списка")
        return

    user_id = message.from_user.id
    data = await state.get_data()

    async with aiosqlite.connect("database.db") as db:
        # Генерируем уникальный номер счета
        account_number = await generate_account_number(db)

        # Сохраняем пользователя
        await db.execute(
            """
            INSERT INTO users 
            (user_id, account_id, name, gender, city, balance) 
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (user_id, account_number, data['name'], data['gender'], city)
        )
        await db.commit()

    # Формируем информационное сообщение
    response = (
        "✅ Регистрация завершена!\n\n"
        "📋 Ваши данные:\n"
        f"├ Имя: {data['name']}\n"
        f"├ Пол: {'Мужской' if data['gender'] == 'м' else 'Женский'}\n"
        f"├ Город: {city}\n"
        f"├ Telegram ID: {user_id}\n"
        f"└ Номер счета: {account_number}\n\n"
        "💳 На ваш счет начислен 1 шуек в подарок!"
    )

    await message.answer(response, reply_markup=ReplyKeyboardRemove())
    await show_main_menu(message, user_id)
    await state.clear()


# Написать заявление
@dp.message(F.text == "📝 Написать заявление")
async def write_statement(message: types.Message, state: FSMContext):
    await state.set_state(Statement.enter_text)
    await message.answer("Пожалуйста, напишите текст заявления:")

@dp.message(Statement.enter_text)
async def save_statement(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("Текст заявления не может быть пустым. Пожалуйста, напишите его снова.")
        return
    user_id = message.from_user.id
    async with aiosqlite.connect("database.db") as db:
        await db.execute(
            "INSERT INTO statements (user_id, text) VALUES (?, ?)",
            (user_id, text)
        )
        await db.commit()

    # Отправляем сообщение админу с заявлением и данными пользователя
    admin_message = (
        f"Новое заявление от пользователя {user_id}:\n\n{text}"
    )
    await bot.send_message(ADMIN_ID, admin_message)

    await message.answer("Ваше заявление сохранено. Спасибо!")
    await show_main_menu(message, user_id)
    await state.clear()

# Записаться ко врачу
@dp.message(F.text == "🧑‍⚕ Записаться ко врачу")
async def start_appointment(message: types.Message, state: FSMContext):
    await message.answer("Выберите врача:", reply_markup=doctors_kb())
    await state.set_state(Appointment.choose_doctor)

@dp.message(Appointment.choose_doctor)
async def choose_time(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await show_main_menu(message, message.from_user.id)
        await state.clear()
        return
    doctor = message.text.strip()
    await state.update_data(doctor=doctor)
    await message.answer("Выберите время:", reply_markup=times_kb())
    await state.set_state(Appointment.choose_time)

@dp.message(Appointment.choose_time)
async def confirm_appointment(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await show_main_menu(message, message.from_user.id)
        await state.clear()
        return
    time = message.text.strip()
    data = await state.get_data()
    doctor = data.get("doctor")
    user_id = message.from_user.id
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT INTO appointments (user_id, doctor, time) VALUES (?, ?, ?)",
                         (user_id, doctor, time))
        await db.commit()
    await message.answer(f"Вы успешно записаны к {doctor} на {time}.")
    await show_main_menu(message, user_id)
    await state.clear()

# Регистрация брака
@dp.message(F.text == "💍 Зарегистрировать брак")
async def start_marriage(message: types.Message, state: FSMContext):
    await state.set_state(Marriage.enter_spouse_account)
    await message.answer(
        "Введите 12-значный номер счета пользователя, с которым хотите вступить в брак:")

@dp.message(Marriage.enter_spouse_account)
async def process_spouse_account(message: types.Message, state: FSMContext):
    spouse_account = message.text.strip()

    # Проверка формата номера счета
    if not (spouse_account.isdigit() and len(spouse_account) == 12):
        await message.answer("❌ Неверный формат номера счета. Введите ровно 12 цифр:")
        return

    user_id = message.from_user.id

    async with aiosqlite.connect("database.db") as db:
        # Получаем account_id текущего пользователя
        cursor = await db.execute(
            "SELECT account_id, name FROM users WHERE user_id = ?",
            (user_id,)
        )
        sender_data = await cursor.fetchone()

        if not sender_data:
            await message.answer("❌ Ваш профиль не найден. Введите /start")
            await state.clear()
            return

        sender_account, sender_name = sender_data

        # Проверяем, не пытается ли пользователь жениться на себе
        if spouse_account == sender_account:
            await message.answer("❌ Вы не можете вступить в брак с самим собой")
            await state.clear()
            return

        # Проверяем существование и статус получателя
        cursor = await db.execute("""
            SELECT user_id, name, spouse_id 
            FROM users 
            WHERE account_id = ?""",
                                  (spouse_account,)
                                  )
        spouse_data = await cursor.fetchone()

        if not spouse_data:
            await message.answer("❌ Пользователь с таким номером счета не найден")
            await state.clear()
            return

        if spouse_data[2] is not None:  # Проверка spouse_id
            await message.answer("❌ Этот пользователь уже состоит в браке")
            await state.clear()
            return

    # Сохраняем данные в state
    await state.update_data(
        spouse_account=spouse_account,
        spouse_user_id=spouse_data[0],
        spouse_name=spouse_data[1],
        sender_account=sender_account,
        sender_name=sender_name)
    # Отправляем запрос
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_marriage:{sender_account}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_marriage:{sender_account}")]])
        await bot.send_message(
            spouse_data[0],  # user_id получателя
            f"💍 Пользователь {sender_name} (счет: {sender_account}) "
            f"хочет вступить с вами в брак. Принять?",
            reply_markup=kb)

        await message.answer(
            f"✅ Запрос на брак отправлен пользователю {spouse_data[1]} "
            f"(счет: {spouse_account}). Ожидайте подтверждения.")
    except Exception as e:
        await message.answer("❌ Не удалось отправить запрос. Возможно, пользователь заблокировал бота")
        print(f"Ошибка отправки запроса на брак: {e}")
    await state.clear()


@dp.callback_query(F.data.startswith("accept_marriage:"))
async def accept_marriage(callback: types.CallbackQuery):
    sender_account = callback.data.split(":")[1]
    acceptor_id = callback.from_user.id

    async with aiosqlite.connect("database.db") as db:
        try:
            # Получаем данные обоих пользователей
            cursor = await db.execute(
                "SELECT user_id, account_id, name FROM users WHERE account_id = ?",
                (sender_account,))
            sender_data = await cursor.fetchone()
            cursor = await db.execute(
                "SELECT account_id, name FROM users WHERE user_id = ?",
                (acceptor_id,))
            acceptor_data = await cursor.fetchone()
            if not sender_data or not acceptor_data:
                await callback.answer("❌ Ошибка: пользователь не найден")
                return

            # Обновляем данные о браке
            await db.execute("BEGIN TRANSACTION")
            await db.execute(
                "UPDATE users SET spouse_id = ? WHERE account_id = ?",
                (acceptor_data[0], sender_account))

            await db.execute(
                "UPDATE users SET spouse_id = ? WHERE user_id = ?",
                (sender_account, acceptor_id))

            await db.commit()

            # Отправляем уведомления
            await bot.send_message(
                sender_data[0],
                f"💕 Ваш брак с {acceptor_data[1]} (счет: {acceptor_data[0]}) успешно зарегистрирован!")

            await bot.send_message(
                acceptor_id,
                f"💕 Вы подтвердили брак с {sender_data[2]} (счет: {sender_account}). Поздравляем!")

        except Exception as e:
            await db.rollback()
            await callback.answer("❌ Произошла ошибка при регистрации брака")
            print(f"Ошибка регистрации брака: {e}")
        finally:
            await callback.message.delete()

@dp.callback_query(F.data.startswith("decline_marriage:"))
async def decline_marriage(callback: types.CallbackQuery):
    sender_account = callback.data.split(":")[1]
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT user_id, name FROM users WHERE account_id = ?",
            (sender_account,))
        sender_data = await cursor.fetchone()
    if sender_data:
        await bot.send_message(
            sender_data[0],
            f"❌ Пользователь {callback.from_user.full_name} отклонил ваше предложение о браке")
    await callback.message.delete()
    await callback.answer("Вы отклонили предложение о браке")

@dp.message(F.text == "💔 Развестись")
async def start_divorce(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    async with aiosqlite.connect("database.db") as db:
        # Получаем данные о браке
        cursor = await db.execute("""
            SELECT u.spouse_id, s.name, s.account_id
            FROM users u
            LEFT JOIN users s ON u.spouse_id = s.account_id
            WHERE u.user_id = ?
            """, (user_id,))
        marriage_data = await cursor.fetchone()
        if not marriage_data or not marriage_data[0]:
            await message.answer("❌ Вы не состоите в браке")
            await show_main_menu(message, user_id)
            return
    await state.update_data(
        spouse_account=marriage_data[0],
        spouse_name=marriage_data[1])
    await message.answer(
        f"⚠️ Вы действительно хотите развестись с {marriage_data[1]} (счет: {marriage_data[2]})?",
        reply_markup=confirm_kb())
    await state.set_state(Divorce.confirm)

@dp.message(Divorce.confirm, F.text == "Подтвердить")
async def confirm_divorce(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    async with aiosqlite.connect("database.db") as db:
        try:
            await db.execute("BEGIN TRANSACTION")
            # Разводим обоих пользователей
            await db.execute(
                "UPDATE users SET spouse_id = NULL WHERE account_id = ?",
                (data['spouse_account'],))

            await db.execute(
                "UPDATE users SET spouse_id = NULL WHERE user_id = ?",
                (user_id,))
            await db.commit()

            # Уведомляем второго участника брака
            cursor = await db.execute(
                "SELECT user_id FROM users WHERE account_id = ?",
                (data['spouse_account'],))
            spouse_id = (await cursor.fetchone())[0]
            await bot.send_message(
                spouse_id,
                f"❌ {message.from_user.full_name} расторг(ла) брак с вами")
            await message.answer(
                "✅ Вы официально разведены.\n"
                f"Брак с {data['spouse_name']} (счет: {data['spouse_account']}) расторгнут.")
        except Exception as e:
            await db.rollback()
            await message.answer("❌ Произошла ошибка при расторжении брака")
            print(f"Ошибка развода: {e}")
        finally:
            await state.clear()
            await show_main_menu(message, user_id)

@dp.message(Divorce.confirm)
async def confirm_divorce(message: types.Message, state: FSMContext):
    if message.text.lower() == "подтвердить":
        user_id = message.from_user.id
        async with aiosqlite.connect("database.db") as db:
            cursor = await db.execute("SELECT spouse_id FROM users WHERE user_id = ?", (user_id,))
            user = await cursor.fetchone()
            if user is None or user[0] is None:
                await message.answer("Вы не состоите в браке.")
                await show_main_menu(message, user_id)
                await state.clear()
                return
            spouse_id = user[0]
            await db.execute("UPDATE users SET spouse_id = NULL WHERE user_id = ?", (user_id,))
            await db.execute("UPDATE users SET spouse_id = NULL WHERE user_id = ?", (spouse_id,))
            await db.commit()
        await message.answer("Вы успешно развелись.")
        await show_main_menu(message, user_id)
        await state.clear()
    else:
        await message.answer("Развод отменён.")
        await show_main_menu(message, message.from_user.id)
        await state.clear()

# Изменить город
@dp.message(F.text == "🏠 Изменить место жительства")
async def change_city_start(message: types.Message, state: FSMContext):
    keyboard = cities_kb()
    keyboard.keyboard.append([KeyboardButton(text="🏘Другой город🏘")])
    await message.answer("Выберите новый город или нажмите '🏘Другой город🏘':", reply_markup=keyboard)
    await state.set_state(ChangeCity.choose_city)

@dp.message(ChangeCity.choose_city)
async def change_city_chosen(message: types.Message, state: FSMContext):
    city = message.text.strip()
    if city == "🏘Другой город🏘":
        await message.answer("Введите ваш город вручную:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(ChangeCity.enter_custom_city)
        return

    allowed_cities = [
        'ФГР. Шуя', 'ФГР. Шуйская Петронезия','Нижний Блаж','ФГР. Аркхем','ФГР. Сабрие', 'ФГР. Лост-Парадайз','Болвания'
    ]
    if city not in allowed_cities:
        await message.answer("Пожалуйста, выберите город из списка или нажмите 'Другой город'.")
        return

    user_id = message.from_user.id
    async with aiosqlite.connect("database.db") as db:
        await db.execute("UPDATE users SET city = ? WHERE user_id = ?", (city, user_id))
        await db.commit()
    await message.answer(f"Ваш город изменён на {city}.", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(message, user_id)
    await state.clear()

@dp.message(ChangeCity.enter_custom_city)
async def change_city_custom_entered(message: types.Message, state: FSMContext):
    city = message.text.strip()
    if not city:
        await message.answer("Название города не может быть пустым. Повторите ввод.")
        return

    user_id = message.from_user.id
    async with aiosqlite.connect("database.db") as db:
        await db.execute("UPDATE users SET city = ? WHERE user_id = ?", (city, user_id))
        await db.commit()
    await message.answer(f"Ваш город изменён на {city}.", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(message, user_id)
    await state.clear()

#смена имени
@dp.message(F.text == "✏️ Изменить имя")
async def start_name_change(message: types.Message, state: FSMContext):
    await message.answer(
        "Введите новое имя (от 2 до 50 символов):",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Settings.waiting_for_new_name)


# Обработчик ввода нового имени
@dp.message(Settings.waiting_for_new_name)
async def process_new_name(message: types.Message, state: FSMContext):
    new_name = message.text.strip()

    # Валидация имени
    if len(new_name) < 2 or len(new_name) > 50:
        await message.answer("Имя должно содержать от 2 до 50 символов. Попробуйте еще раз.")
        return

    user_id = message.from_user.id

    async with aiosqlite.connect("database.db") as db:
        # Обновляем имя в базе данных
        await db.execute(
            "UPDATE users SET name = ? WHERE user_id = ?",
            (new_name, user_id)
        )
        await db.commit()

        # Получаем обновленные данные для отображения
        cursor = await db.execute(
            "SELECT name, account_id FROM users WHERE user_id = ?",
            (user_id,)
        )
        updated_user = await cursor.fetchone()

    if updated_user:
        await message.answer(
            f"✅ Ваше имя успешно изменено на: {updated_user[0]}\n"
            f"Номер счета: {updated_user[1]}"
        )
    else:
        await message.answer("❌ Произошла ошибка при изменении имени")

    await state.clear()
    await show_main_menu(message, user_id)


# Обновляем функцию show_main_menu для отображения кнопки
async def show_main_menu(message: types.Message, user_id: int):
    """Показывает главное меню с полной информацией о пользователе"""
    async with aiosqlite.connect("database.db") as db:
        # Получаем ВСЕ необходимые данные за один запрос
        cursor = await db.execute("""
            SELECT 
                u.name, u.gender, u.city, u.balance, u.account_id,
                u.spouse_id, s.name as spouse_name
            FROM users u
            LEFT JOIN users s ON u.spouse_id = s.account_id
            WHERE u.user_id = ?
            """, (user_id,))
        user = await cursor.fetchone()

    if not user:
        await message.answer("❌ Профиль не найден. Введите /start для регистрации")
        return

    # Распаковываем все полученные данные
    name, gender, city, balance, account_id, spouse_id, spouse_name = user

    # Формируем сообщение с использованием ВСЕХ полученных данных
    profile_info = (
        f"📕 <b>Паспорт {name}</b>\n\n"
        f"💛├ 🆔 <b>Гос ID:</b> <code>{account_id}</code>\n"
        f"💛├ 👤 <b>Имя:</b> <code>{name}</code>\n"
        f"🤍├ 👫 <b>Пол:</b> <code>{'Мужской' if gender == 'м' else 'Женский'}</code>\n"
        f"🤍├ 💍 <b>Супруг(а):</b> <code>{spouse_name if spouse_name else 'Нет'}</code>\n"
        f"💙├ 🏙 <b>Город:</b> <code>{city}</code>\n"
        f"💙└ 💳 <b>Баланс:</b> <code>{balance}</code> шуек\n"
    )

    # Отправляем отформатированное сообщение
    await message.answer(profile_info, parse_mode="HTML")

    # Показываем меню с учетом наличия супруга
    await message.answer(
        "Выберите действие:",
        reply_markup=main_menu_kb(spouse_exists=bool(spouse_id)))

# Переводы
@dp.message(F.text == "💰 Новый перевод")
async def start_transfer(message: types.Message, state: FSMContext):
    await message.answer("Введите 12-значный номер счета получателя:")
    await state.set_state(Transfer.enter_recipient)


@dp.message(Transfer.enter_recipient)
async def transfer_enter_amount(message: types.Message, state: FSMContext):
    recipient_account = message.text.strip()

    # Проверка формата 12 цифр
    if not recipient_account.isdigit() or len(recipient_account) != 12:
        await message.answer("Некорректный номер счета. Должно быть 12 цифр.")
        return

    user_id = message.from_user.id

    async with aiosqlite.connect("database.db") as db:
        # Проверяем существование получателя
        cursor = await db.execute(
            "SELECT 1 FROM users WHERE account_id = ?",
            (recipient_account,)
        )
        recipient_exists = await cursor.fetchone()

        if not recipient_exists:
            await message.answer("Пользователь с таким номером счета не найден.")
            return

        # Проверяем что не переводим себе
        cursor = await db.execute(
            "SELECT account_id FROM users WHERE user_id = ?",
            (user_id,)
        )
        sender_account = (await cursor.fetchone())[0]

        if sender_account == recipient_account:
            await message.answer("Вы не можете перевести деньги себе.")
            return

    await state.update_data(recipient_account=recipient_account)
    await message.answer("Введите сумму перевода (целое число):")
    await state.set_state(Transfer.enter_amount)


@dp.message(Transfer.enter_amount)
async def transfer_confirm(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Некорректная сумма. Введите положительное целое число.")
        return

    data = await state.get_data()
    recipient_account = data.get("recipient_account")
    user_id = message.from_user.id

    async with aiosqlite.connect("database.db") as db:
        # Получаем все необходимые данные за один запрос
        cursor = await db.execute(
            """SELECT u1.balance, u1.city, u2.city 
               FROM users u1, users u2 
               WHERE u1.user_id = ? AND u2.account_id = ?""",
            (user_id, recipient_account)
        )
        sender_balance, sender_city, recipient_city = await cursor.fetchone()

        # Проверяем достаточность средств
        commission = 0 if sender_city.startswith("ФГР") and recipient_city.startswith("ФГР") else 1
        total_amount = amount + commission

        if sender_balance < total_amount:
            await message.answer(f"Недостаточно средств:(\n На вашем счету: {sender_balance} шуек.")
            await state.clear()
            return

        text = (f"Вы собираетесь перевести {amount} шуек на счет {recipient_account}\n"
                f"Комиссия: {commission} шуйка\n"
                f"Итого будет списано: {total_amount} шуек\n"
                f"Остаток после перевода: {sender_balance - total_amount} шуек")

        await state.update_data(
            amount=amount,
            commission=commission,
            total_amount=total_amount,
            recipient_account=recipient_account
        )
        await message.answer(text, reply_markup=confirm_kb())
        await state.set_state(Transfer.confirm)


@dp.message(Transfer.confirm, F.text == "Подтвердить")
async def execute_transfer(message: types.Message, state: FSMContext):
    user_id = message.from_user.id  # Получаем user_id
    data = await state.get_data()
    user_id = message.from_user.id
    amount = data['amount']
    commission = data['commission']
    total_amount = data['total_amount']
    recipient_account = data['recipient_account']

    async with aiosqlite.connect("database.db") as db:
        try:
            # Начинаем транзакцию
            await db.execute("BEGIN TRANSACTION")

            # Списание у отправителя
            await db.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                (total_amount, user_id, total_amount)
            )

            # Зачисление получателю (без комиссии)
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE account_id = ?",
                (amount, recipient_account)
            )

            # Запись в историю переводов
            await db.execute(
                """INSERT INTO transfers (from_user, to_user, amount, commission) 
                   VALUES ((SELECT account_id FROM users WHERE user_id = ?), ?, ?, ?)""",
                (user_id, recipient_account, amount, commission)
            )

            await db.commit()

            await message.answer(
                f"Перевод успешно выполнен!\n"
                f"Переведено: {amount} шуек\n"
                f"Комиссия: {commission} шуйка"
            )

        except Exception as e:
            await db.rollback()
            await message.answer("Произошла ошибка при переводе. Попробуйте позже.")
            print(f"Transfer error: {e}")
        finally:
            await state.clear()
            await show_main_menu(message, user_id)

@dp.message(Transfer.confirm, F.text == "Отмена")
async def cancel_transfer(message: types.Message, state: FSMContext):
    await message.answer("Перевод отменён.")
    await state.clear()
    await show_main_menu(message, message.from_user.id)



#истории
# Обработчик кнопки Истории
@dp.message(F.text == "📂 Истории")
async def open_history_menu(message: types.Message):
    await message.answer("Выберите тип истории:", reply_markup=history_menu_kb())

# История переводов
@dp.message(F.text == "📜 История переводов")
async def transfer_history(message: types.Message):
    user_id = message.from_user.id

    async with aiosqlite.connect("database.db") as db:
        # Получаем account_id текущего пользователя
        cursor = await db.execute(
            "SELECT account_id FROM users WHERE user_id = ?",
            (user_id,)
        )
        user_account = await cursor.fetchone()

        if not user_account:
            await message.answer("❌ Ошибка: ваш аккаунт не найден")
            return

        account_id = user_account[0]

        # Получаем полную историю переводов с именами получателей (без LIMIT)
        cursor = await db.execute("""
            SELECT t.amount, t.timestamp, t.to_user, u.name 
            FROM transfers t
            LEFT JOIN users u ON t.to_user = u.account_id
            WHERE t.from_user = ?
            ORDER BY t.timestamp DESC
        """, (account_id,))

        transfers = await cursor.fetchall()

    if not transfers:
        await message.answer("📭 История переводов пуста")
        return

    # Разбиваем историю на части, если она слишком большая
    chunk_size = 30  # Количество переводов в одном сообщении
    chunks = [transfers[i:i + chunk_size] for i in range(0, len(transfers), chunk_size)]

    for chunk_num, chunk in enumerate(chunks, 1):
        response = f"📜 История переводов (часть {chunk_num}):\n\n"
        for idx, (amount, timestamp, to_account, to_name) in enumerate(chunk, 1):
            recipient = to_name if to_name else f"Аккаунт {to_account[:4]}...{to_account[-4:]}"
            response += (
                f"{idx}. {timestamp[:16]}\n"
                f"→ {recipient}\n"
                f"Сумма: {amount} шуек\n"
                f"───────────────────\n"
            )

        # Если это последний кусок и он почти полный - не добавляем "Продолжение следует"
        if chunk_num < len(chunks) or len(chunk) >= chunk_size - 2:
            response += "\n⬇️ Продолжение следует..."

        await message.answer(response)

# История заявлений
@dp.message(F.text == "📄 История заявлений")
async def statement_history(message: types.Message):
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT text, timestamp FROM statements WHERE user_id = ?", (message.from_user.id,))
        rows = await cursor.fetchall()
    if not rows:
        await message.answer("История заявлений пуста.")
    else:
        text = "📄 История заявлений:\n"
        for content, timestamp in rows:
            text += f"• {timestamp}: {content}\n"
        await message.answer(text)
# История записей ко врачу
@dp.message(F.text == "🧑‍⚕ История записей ко врачу")
async def appointment_history(message: types.Message):
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT doctor, time, timestamp FROM appointments WHERE user_id = ?", (message.from_user.id,))
        rows = await cursor.fetchall()
    if not rows:
        await message.answer("История записей пуста.")
    else:
        text = "🧑‍⚕ История записей ко врачу:\n"
        for doctor, time, timestamp in rows:
            text += f"• {doctor} в {time} | {timestamp}\n"
        await message.answer(text)
# Обработчик кнопки Назад из меню истории
@dp.message(F.text == "↩ Назад")
async def back_to_main_from_history(message: types.Message):
    await show_main_menu(message, message.from_user.id)


"""
АДМИИИИИИИН
"""
@dp.message(Command("set_balance"))
async def handle_set_balance_command(message: types.Message, state: FSMContext):
    admin_ids = [6313754974]
    if message.from_user.id not in admin_ids:
        await message.answer("У вас нет прав для выполнения этой команды.")
        return
    await message.answer("Пожалуйста, отправьте ID пользователя, чей баланс нужно изменить:")
    await state.set_state(SetBalance.waiting_for_user_id)

@dp.message(StateFilter(SetBalance.waiting_for_user_id))
async def handle_user_id(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        await state.update_data(user_id=user_id)
        await message.answer("Введите новый баланс:")
        await state.set_state(SetBalance.waiting_for_balance)
    except ValueError:
        await message.answer("Пожалуйста, введите корректный числовой ID пользователя.")

@dp.message(StateFilter(SetBalance.waiting_for_balance))
async def handle_new_balance(message: types.Message, state: FSMContext):
    try:
        new_balance = int(message.text.strip())
        data = await state.get_data()
        user_id = data['user_id']
        async with aiosqlite.connect("database.db") as db:
            await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
            await db.commit()
        await message.answer(f"Баланс пользователя {user_id} успешно обновлён на {new_balance}.")
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число для баланса.")
@dp.message(Command("users"))
async def handle_list_users(message: types.Message):
    admin_ids = [6313754974]  # сюда добавь ID админов, кому разрешен доступ
    if message.from_user.id not in admin_ids:
        await message.answer("У вас нет прав для этой команды.")
        return
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT user_id, name, balance, city FROM users")
        users = await cursor.fetchall()
    if not users:
        await message.answer("Пользователи не найдены.")
        return
    text = "Список пользователей:\n"
    for user_id, name, balance, city in users:
        text += f"ID: {user_id}\nИмя: {name}\n-----Баланс: {balance}\n-----Город: {city}\n\n"
    await message.answer(text)

#рассылка
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    admin_ids = [ADMIN_ID]  # Используем уже определенный ADMIN_ID
    if message.from_user.id not in admin_ids:
        await message.answer("У вас нет прав для выполнения этой команды.")
        return

    await message.answer(
        "Введите сообщение для рассылки всем пользователям:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Broadcast.waiting_for_message)


@dp.message(Broadcast.waiting_for_message)
async def process_broadcast_message(message: types.Message, state: FSMContext):
    await state.update_data(broadcast_message=message.text)
    await message.answer(
        f"Подтвердите рассылку следующего сообщения:\n\n{message.text}",
        reply_markup=confirm_kb()  # Используем уже существующую клавиатуру подтверждения
    )
    await state.set_state(Broadcast.confirm)


# Обработчик подтверждения рассылки
@dp.message(Broadcast.confirm, F.text == "Подтвердить")
async def confirm_broadcast(message: types.Message, state: FSMContext):
    data = await state.get_data()
    broadcast_message = data.get("broadcast_message")

    if not broadcast_message:
        await message.answer("Ошибка: сообщение не найдено.")
        await state.clear()
        await show_main_menu(message, message.from_user.id)  # Возврат в меню
        return

    await message.answer("⏳ Начинаю рассылку сообщения...", reply_markup=ReplyKeyboardRemove())

    successful = 0
    failed = 0

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT user_id FROM users")
        users = await cursor.fetchall()

        for (user_id,) in users:
            try:
                await bot.send_message(
                    user_id,
                    f"📢 Важное сообщение от администрации:\n\n{broadcast_message}"
                )
                successful += 1
            except Exception as e:
                print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
                failed += 1
            await asyncio.sleep(0.1)

    await message.answer(
        f"✅ Рассылка завершена:\n"
        f"Успешно: {successful}\n"
        f"Не удалось: {failed}"
    )
    await state.clear()
    await show_main_menu(message, message.from_user.id)  # Возврат в главное меню


# Обработчик отмены рассылки
@dp.message(Broadcast.confirm, F.text == "Отмена")
async def cancel_broadcast(message: types.Message, state: FSMContext):
    await message.answer("Рассылка отменена.", reply_markup=ReplyKeyboardRemove())
    await state.clear()
    await show_main_menu(message, message.from_user.id)  # Возврат в главное меню


# Обработчик отмены рассылки
@dp.message(Broadcast.confirm, F.text == "Отмена")
async def cancel_broadcast(message: types.Message, state: FSMContext):
    await message.answer("Рассылка отменена.")
    await state.clear()

"""
ДЕПОРТРАТОР
"""
@dp.message(Command("deportation"))
async def deport_user(message: types.Message):
    if not message.reply_to_message:
        await message.answer("Эта команда должна быть ответом на сообщение пользователя.")
        return

    target_user_id = message.reply_to_message.from_user.id
    deportation_places = [
        "ФГР. Шуя",
        "Психо-Неврологический Диспанцер имени Михаила Бабушкина",
        "Шуйско-Болванский мост",
        "Болвания",
        "Улица",
        "Шахта"
    ]
    new_place = random.choice(deportation_places)

    async with aiosqlite.connect("database.db") as db:
        await db.execute("UPDATE users SET city = ? WHERE user_id = ?", (new_place, target_user_id))
        await db.commit()

    await message.answer(f"Пользователь {message.reply_to_message.from_user.full_name} депортирован. \nНовое место жительства {message.reply_to_message.from_user.full_name} теперь: {new_place}.")

# помощь
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """
🆘 <b>Список доступных команд:</b> 🆘

/start - Регистрация и показ главного меню (работает только в личных сообщениях)
/help - Показывает это сообщение (работает в личных сообщениях и группах)
/my_passport - показать свой паспорт (работает в личных сообщениях и группах)
/deportation - депортирование пользователя, на чьё сообщение вы ответили (работает в личных сообщениях и группах)

📌 <i>Если что-то не работает, пишите заявление в боте (кнопка: "📝 Написать заявление")
    """
    await message.answer(help_text, parse_mode="HTML")
"""


показ паспорта
"""
async def my_passport_get(user_id):
    try:
        async with aiosqlite.connect("database.db") as db:
            cursor = await db.execute("""
                SELECT 
                    u.name, u.gender, u.city, u.balance, u.account_id,
                    u.spouse_id, s.name as spouse_name
                FROM users u
                LEFT JOIN users s ON u.spouse_id = s.account_id
                WHERE u.user_id = ?
                """, (user_id,))
            user = await cursor.fetchone()

            if not user:
                return None  # Пользователь не найден

            name, gender, city, balance, account_id, spouse_id, spouse_name = user

            profile_info = (
                f"📕 <b>Паспорт пользователя {name}</b>\n\n"
                f"💛├ 🆔 <b>Гос ID:</b> <code>{account_id}</code>\n"
                f"💛├ 👤 <b>Имя:</b> <code>{name}</code>\n"
                f"🤍├ 👫 <b>Пол:</b> <code>{'Мужской' if gender == 'м' else 'Женский'}</code>\n"
                f"🤍├ 💍 <b>Супруг(а):</b> <code>{spouse_name or 'Нет'}</code>\n"
                f"💙├ 🏙 <b>Город:</b> <code>{city}</code>\n"
                f"💙└ 💳 <b>Баланс:</b> <code>{balance}</code> шуек\n"
            )
            return profile_info
    except Exception as e:
        print(f"Ошибка при получении паспорта: {e}")
        return None

#мой паспорт
@dp.message(F.text.in_(["/my_passport", "/mp"]))
async def send_passport(message: types.Message):
    user_id = message.from_user.id
    current_time = datetime.now()

    # Проверяем, когда пользователь последний раз использовал команду
    if user_id in last_used:
        last_time = last_used[user_id]
        if current_time - last_time < timedelta(seconds=10):
            remaining = 10 - (current_time - last_time).seconds
            await message.answer(f"⏳ Подождите {remaining} секунд перед повторным запросом!")
            return

    # Обновляем время и выполняем команду
    last_used[user_id] = current_time
    passport_info = await my_passport_get(user_id)

    if passport_info:
        await message.answer(passport_info, parse_mode="HTML")
    else:
        await message.answer("❌ Данные паспорта не найдены.")


async def main():
    await dp.start_polling(bot)



if __name__ == "__main__":
    import asyncio

    async def main():
        await init_db()  # если у тебя есть инициализация БД
        await dp.start_polling(bot)

    asyncio.run(main())
