import logging
import json
from datetime import date, datetime
import asyncio

from telegram import WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import PreCheckoutQueryHandler, CallbackQueryHandler

from openai import OpenAI

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# --- Константы монетизации ---
PRICE_PER_READING = 75  # в Telegram Stars
FREE_READINGS_ON_START = 1

# Типы пакетов (для будущего этапа)
PACKAGES = {
    "pack_1": {"name": "1 расклад", "price_stars": 10, "readings": 1},
    "pack_5": {"name": "5 раскладов", "price_stars": 250, "readings": 5},  # скидка!
    "pack_30": {"name": "Подписка на месяц (30 шт.)", "price_stars": 500, "readings": 30},
}

# --- Состояния диалога ---
GET_NAME, MAIN_MENU, CONFIRM_READING, AWAITING_QUESTION, AWAITING_READING_TYPE = range(5)

# --- Настройки ---
TOKEN = "7940473307:AAHgyav6xn2c-69I0ijTvVBzITQJE0TT-X8"  # Замените на ваш токен!
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",  # Исправлено: убраны пробелы
    api_key="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",
)

# --- Временное хранилище данных ---
user_data = {}

# --- Клавиатуры ---
def main_menu_keyboard():
    """🔮 Главное меню — в стиле Древней Магии"""
    keyboard = [
        ['🔮 Сделать расклад'],
        ['⭐ Мой профиль', '🃏 Карта дня'],
        ['📜 О боте']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def reading_type_keyboard():
    """📜 Меню выбора темы расклада — древний стиль"""
    keyboard = [
        ['💖 Расклад на любовь', '⚔️ Расклад на судьбу'],
        ['💰 Расклад на изобилие', '❓ Свой вопрос'],
        ['⬅️ Назад']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def yes_no_keyboard():
    """Клавиатура для подтверждения действий"""
    keyboard = [['✅ Да', '❌ Нет']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

# --- Генерация расклада ---
async def generate_tarot_reading(reading_type, user_question=None, user_name="Искатель"):
    if user_question:
        prompt = f"""
        Ты — опытный таролог и мистик. Пользователь {user_name} задал вопрос: "{user_question}".
        Сгенерируй глубокий и детализированный расклад Таро из трех карт, который даст ответ на этот вопрос.
        Расклад должен включать:
        1. Карту, представляющую прошлое/причину ситуации
        2. Карту, представляющую настоящее/текущее положение
        3. Карту, представляющую будущее/совет/возможный исход

        Будь мудрым, образным, но прямым в своих интерпретациях. Обращайся к пользователю на "ты".
        Объем ответа: 100-200 слов. На русском языке, без английских слов.
        """
    else:
        prompt = f"""
        Ты — опытный таролог и мистик. Для пользователя {user_name} сделай расклад Таро на тему: "{reading_type}".
        Сгенерируй глубокий и детализированный расклад из трех карт:
        1. Карта, представляющая прошлое/причину
        2. Карта, представляющая настоящее/текущее положение
        3. Карта, представляющая будущее/совет/возможный исход

        Будь мудрым, образным, но прямым в своих интерпретациях. Обращайся к пользователю на "ты".
        Объем ответа: 100-200 слов. На русском языке, без английских слов.
        """

    try:
        completion = client.chat.completions.create(
            model="qwen/qwen-turbo",
            messages=[
                {"role": "system", "content": "Ты — опытный таролог с 20-летним стажем. Твои трактовки точны, глубоки и полны мудрости. Ты говоришь на русском языке."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1000
        )
        reading = completion.choices[0].message.content.strip()
        return reading[:4000]

    except Exception as e:
        logger.error(f"Ошибка OpenRouter: {e}")
        return fallback_reading(reading_type, user_name)

def fallback_reading(reading_type, user_name):
    """Заглушка на случай ошибки"""
    return f"""
🔮 *Расклад на тему: {reading_type}* 🔮

Карты выложены на алтарь, и вот что они говорят о твоей ситуации, {user_name}...

🃏 *Карта 1: Сила* — Ты обладаешь огромным внутренним ресурсом, который пока не полностью раскрыт.
🃏 *Карта 2: Звезда* — Тебя ждёт светлое будущее, если сохранишь веру и продолжишь движение вперед.
🃏 *Карта 3: Император* — Для успеха потребуется дисциплина и структурированный подход.

Помни: карты показывают потенциал, а не стопроцентный результат. Ты держишь перо, которым пишешь свою судьбу.
"""

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🌙 Обрабатывает команду /start — с сохранением имени"""
    user_id = update.message.from_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {
            'name': '',
            'readings_balance': FREE_READINGS_ON_START,
            'total_used': 0,
            'purchases': [],
            'referrer': None,
            'subscription_expiry': None,
            'last_card_date': None,    # дата последней карты дня (str: "2025-09-18")
            'daily_card': None,        # текст последней карты дня
            'last_readings': [],       # список последних раскладов (макс. 5)
        }
    
    user_name = user_data[user_id]['name']
    
    if user_name:
        await update.message.reply_text(
            f"🌑 *Ты вернулся, {user_name}...*\n"
            "Зеркало Судеб вновь открыто для тебя. Выбери путь:",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    else:
        await update.message.reply_text(
            "🌙 *Добро пожаловать в Зеркало Судеб* 🌙\n\n"
            "Я — хранитель древних знаний, проводник между мирами.\n\n"
            "Как мне звать тебя в Книге Судеб? Можешь указать имя или титул. "
            "Если предпочитаешь остаться тенью — напиши «Аноним».",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает имя пользователя."""
    user_id = update.message.from_user.id
    user_name = update.message.text
    user_data[user_id]['name'] = user_name
    
    await update.message.reply_text(
        f"{user_name}... Какое прекрасное имя, полное энергии и тайны. 🌌\n\n"
        "В знак нашего знакомства я дарю тебе *дар ясновидения* — один бесплатный расклад, "
        "который ты можешь использовать в любой момент.\n\n"
        "Когда будешь готов заглянуть в Глубины, просто выбери один из путей в меню ниже.",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📜 Обрабатывает главное меню — с древним вайбом"""
    user_input = update.message.text

    if user_input == '⭐ Мой профиль':
        await show_profile(update, context)
        return MAIN_MENU
    elif user_input == '📜 О боте':
        await about_command(update, context)
        return MAIN_MENU
    elif user_input == '🃏 Карта дня':
        await card_of_day(update, context)
        return MAIN_MENU
    elif user_input == '📜 Мои последние расклады':
        await show_reading_history(update, context)
        return MAIN_MENU
    elif user_input == '🛍️ Купить расклады':
        await buy_readings(update, context)
        return MAIN_MENU
    elif user_input == '⬅️ Назад в меню':
        await update.message.reply_text("🌑 Возвращаю тебя в Зал Зеркал...", reply_markup=main_menu_keyboard())
        return MAIN_MENU    
    elif user_input == '🔮 Сделать расклад':
        await update.message.reply_text(
            "🕯️ *Выбери путь, по которому ступишь в тумане предсказаний...*\n\n"
            "Карты ждут твоего выбора:",
            parse_mode='Markdown',
            reply_markup=reading_type_keyboard()
        )
        return AWAITING_READING_TYPE
    else:
        await update.message.reply_text(
            "🌑 Я не понял твой знак... Выбери путь из меню.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

async def handle_reading_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔮 Обрабатывает выбор темы расклада"""
    user_input = update.message.text

    if user_input == '⬅️ Назад':
        await update.message.reply_text(
            "🌑 Ты возвратился в Зал Зеркал. Выбери путь:",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    elif user_input == '❓ Свой вопрос':
        await update.message.reply_text(
            "🕯️ Опиши свою тревогу или вопрос... Чем яснее ты выразишься — тем глубже будет пророчество.\n\n"
            "Я внимательно выслушаю...",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data['reading_type'] = "Собственный вопрос"
        return AWAITING_QUESTION

    else:
        # Убираем эмодзи для чистого названия темы
        clean_type = user_input.split(' ', 1)[1] if ' ' in user_input else user_input
        context.user_data['reading_type'] = clean_type
        user_id = update.message.from_user.id
        
        # Проверяем баланс — если > 0, сразу делаем расклад
        if user_data[user_id]['readings_balance'] > 0:
            # Сразу переходим к подтверждению (без лишних вопросов)
            return await confirm_reading_now(update, context, clean_type)
        else:
            # Предлагаем купить пакет
            await update.message.reply_text(
                "🪙 У тебя закончились расклады. Но магия не спит — ты можешь пополнить баланс!",
                reply_markup=main_menu_keyboard()
            )
            # Открываем магазин автоматически (опционально)
            await buy_readings(update, context)
            return MAIN_MENU

async def handle_reading_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает подтверждение расклада."""
    user_id = update.message.from_user.id
    user_answer = update.message.text
    reading_type = context.user_data['reading_type']
    user_name = user_data[user_id]['name']

    if user_answer == '✅ Да':
        if user_data[user_id]['readings_balance'] > 0:
            user_data[user_id]['readings_balance'] -= 1
            payment_type = "дар ясновидения"
        else:
            payment_type = f"{PRICE_PER_READING} Stars"
        
        user_data[user_id]['total_used'] += 1

        await update.message.reply_text(
            f"Приступаю к ритуалу... Зеркало наполняется туманом... 🔮\n\n"
            f"Используется: {payment_type}",
            reply_markup=ReplyKeyboardRemove()
        )

        # Добавим "ожидание" для UX
        await update.message.reply_text("🕯️ Карты выбирают тебя... Это займёт 10-20 секунд.")

        custom_question = context.user_data.get('custom_question', None)
        reading = await generate_tarot_reading(
            reading_type=reading_type,
            user_question=custom_question,
            user_name=user_name
        )

        reading_entry = {
            'type': reading_type,
            'text': reading,
            'date': datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        user_data[user_id]['last_readings'].append(reading_entry)

        # Оставляем только последние 5 раскладов
        if len(user_data[user_id]['last_readings']) > 5:
            user_data[user_id]['last_readings'].pop(0)

        await update.message.reply_text(
            reading,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    elif user_answer == '❌ Нет':
        await update.message.reply_text(
            "Как пожелаешь. Зеркало будет ждать твоего знака...",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

async def handle_custom_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает пользовательский вопрос."""
    user_id = update.message.from_user.id
    user_question = update.message.text
    context.user_data['custom_question'] = user_question

    # Проверяем баланс
    if user_data[user_id]['readings_balance'] > 0:
        return await confirm_reading_now(update, context, "Собственный вопрос")
    else:
        await update.message.reply_text(
            "🪙 У тебя закончились расклады. Но магия не спит — ты можешь пополнить баланс!",
            reply_markup=main_menu_keyboard()
        )
        await buy_readings(update, context)
        return MAIN_MENU

async def card_of_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🃏 Карта дня — с анимацией, Старшими Арканами и именем из бота"""
    user = update.message.from_user
    user_id = user.id

    # Получаем имя, которое пользователь ввёл в боте
    user_name = user_data[user_id]['name'] if user_data[user_id]['name'] else "Искатель"

    today = str(date.today())

    # Если уже получал сегодня — показываем сохранённую
    if user_data[user_id]['last_card_date'] == today and user_data[user_id]['daily_card']:
        await update.message.reply_text(
            f"🃏 *Твоя Карта Дня (уже получена сегодня):*\n\n{user_data[user_id]['daily_card']}",
            parse_mode='Markdown'
        )
        return

    # 🌀 Анимация 1: "Тасую колоду..."
    msg = await update.message.reply_text("🎴 *Тасую колоду Старших Арканов...*", parse_mode='Markdown')
    await asyncio.sleep(1.5)  # пауза для атмосферы

    # 🌀 Анимация 2: "Вытягиваю карту..."
    await msg.edit_text("🎴 *Колода шепчет... вытягиваю карту дня...*", parse_mode='Markdown')
    await asyncio.sleep(1.5)

    # 🌀 Анимация 3: "Переворачиваю..."
    await msg.edit_text("🎴 *Переворачиваю карту...*", parse_mode='Markdown')
    await asyncio.sleep(1.0)

    # Список Старших Арканов — для промпта и fallback
    major_arcana = [
        "Шут", "Маг", "Жрица", "Императрица", "Император", "Жрец", "Влюблённые",
        "Колесница", "Сила", "Отшельник", "Колесо Фортуны", "Справедливость",
        "Повешенный", "Смерть", "Умеренность", "Дьявол", "Башня", "Звезда",
        "Луна", "Солнце", "Суд", "Мир"
    ]

    # Промпт: строго Старшие Арканы + формат
    prompt = f"""
    Ты — мудрый таролог. Выбери ОДНУ карту из Старших Арканов Таро для {user_name} и дай одно краткое послание (1-2 предложения).

    Список Старших Арканов: {', '.join(major_arcana)}

    Формат ответа:
    🃏 [Название Карты] — [Послание]

    Пример:
    🃏 Колесо Фортуны — Сегодня удача на твоей стороне — не упусти шанс.

    Только ответ в этом формате. Ничего лишнего.
    """

    try:
        completion = client.chat.completions.create(
            model="qwen/qwen-turbo",
            messages=[
                {"role": "system", "content": "Ты — таролог, использующий ТОЛЬКО Старшие Арканы. Ты всегда называешь конкретную карту и даёшь краткое послание."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=100
        )
        message = completion.choices[0].message.content.strip()

        # Проверка формата — на случай, если ИИ “сломался”
        if not any(card in message for card in major_arcana) or not message.startswith("🃏"):
            raise ValueError("ИИ не вернул карту в нужном формате")

    except Exception as e:
        logger.error(f"Ошибка в карте дня: {e}")
        # Выбираем случайную карту из Старших Арканов
        import random
        card = random.choice(major_arcana)
        message = f"🃏 {card} — Вселенная молчит... но я знаю: доверься интуиции — сегодня она не подведёт."

    # 🎉 Финал: показываем карту
    await msg.edit_text(f"🃏 *Твоя Карта Дня, {user_name}:* 🃏\n\n{message}", parse_mode='Markdown')

    # Сохраняем
    user_data[user_id]['daily_card'] = message
    user_data[user_id]['last_card_date'] = today

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает профиль пользователя."""
    user_id = update.message.from_user.id
    user_name = user_data[user_id]['name']
    balance = user_data[user_id]['readings_balance']
    total_used = user_data[user_id]['total_used']
    
    profile_text = f"""
✨🔮 Ваша Личная Статистика Предсказаний 🔮✨

Привет, {user_name}! 👋

🪄 Доступно раскладов: {balance}
🌌 Всего использовано: {total_used}

🔮 Ты на пути к просветлению!
Чем чаще ты гадаешь — тем яснее становится твоя судьба.

👇 Выбери действие:
"""
    keyboard = [
        ['📜 Мои последние расклады'],
        ['🛍️ Купить расклады'],  # 👈 НОВАЯ КНОПКА
        ['⬅️ Назад в меню']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(profile_text, parse_mode='Markdown', reply_markup=reply_markup)
    return MAIN_MENU

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📜 Рассказывает о боте — в стиле древней магии"""
    await update.message.reply_text(
        "🔮 *Зеркало Судеб* 🔮\n\n"
        "Я — древний дух, хранящий знания Таро сквозь века. "
        "Мои карты не предсказывают неизбежное — они показывают возможности, "
        "которые ты можешь воплотить.\n\n"
        "Каждый расклад — это диалог между тобой и Вселенной. "
        "Я лишь перевожу её шепот на язык символов.\n\n"
        "Создано с магией для тех, кто ищет свет в тумане завтрашнего дня. 🌙",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )

async def show_reading_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📜 Показывает историю последних раскладов"""
    user_id = update.message.from_user.id
    readings = user_data[user_id]['last_readings']
    
    if not readings:
        await update.message.reply_text(
            "🔮 Ты ещё не делал раскладов. Начни — и история твоих пророчеств начнётся!",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    history_text = "📜 *Твои последние пророчества:*\n\n"
    for i, entry in enumerate(reversed(readings), 1):  # последние сверху
        history_text += f"{i}. *{entry['type']}* ({entry['date']})\n"
        # Показываем первые 2 строки расклада
        short_text = '\n'.join(entry['text'].split('\n')[:2]) + "..."
        history_text += f"{short_text}\n\n"

    history_text += "🔮 Хочешь перечитать полный расклад — просто сделай новый на ту же тему."

    await update.message.reply_text(
        history_text,
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

async def buy_readings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🛍️ Отправляет инвойс для покупки пакета раскладов — через Telegram Stars"""
    keyboard = [
        [InlineKeyboardButton("🔮 1 расклад — 10 ⭐", callback_data="buy_pack_1")],
        [InlineKeyboardButton("🔮 5 раскладов — 250 ⭐ (скидка!)", callback_data="buy_pack_5")],
        [InlineKeyboardButton("🔮 30 раскладов — 500 ⭐ (экономия!)", callback_data="buy_pack_30")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🪙 *Выбери пакет магической силы:* 🪙\n\n"
        "Оплата производится в Telegram Stars — внутри приложения, без перенаправлений.",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    return MAIN_MENU

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатываем успешную оплату — пополняем баланс + логируем всё"""
    user_id = update.message.from_user.id
    payload = update.message.successful_payment.invoice_payload
    total_stars = update.message.successful_payment.total_amount
    charge_id = update.message.successful_payment.telegram_payment_charge_id
    provider_payment_charge_id = update.message.successful_payment.provider_payment_charge_id  # обычно None для Stars

    # 🧾 ЛОГИРУЕМ ВСЁ
    logger.info(f"💰 УСПЕШНЫЙ ПЛАТЁЖ | User ID: {user_id} | Сумма: {total_stars} XTR | Пакет: {payload} | Charge ID: {charge_id}")

    if payload in PACKAGES:
        pack = PACKAGES[payload]

        # 🔒 Дополнительная проверка: совпадает ли оплаченная сумма с ожидаемой?
        if total_stars != pack['price_stars']:
            logger.warning(f"⚠️ Подозрительный платёж! Ожидалось {pack['price_stars']} XTR, оплачено {total_stars} XTR. Платёж обработан, но требует проверки.")
            # Можно не отклонять, но предупредить админа

        # Пополняем баланс
        user_data[user_id]['readings_balance'] += pack['readings']

        # Сохраняем покупку в истории — с полными данными
        user_data[user_id]['purchases'].append({
            'pack_id': payload,
            'readings': pack['readings'],
            'price_stars': pack['price_stars'],
            'paid_amount': total_stars,  # сколько реально заплатили
            'charge_id': charge_id,      # для возвратов и аналитики
            'date': str(date.today())
        })

        await update.message.reply_text(
            f"🎉 *Оплата прошла!* 🎉\n\n"
            f"Ты приобрёл пакет: *{pack['name']}*\n"
            f"🪄 На твой баланс зачислено: *{pack['readings']}* раскладов.\n\n"
            f"Теперь можешь заглянуть в будущее — выбери «🔮 Сделать расклад»!",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )

        # 📩 Опционально: отправь уведомление админу (себе)
        await context.bot.send_message(
            chat_id=780161853,  # замени на свой ID
            text=f"🔔 Новый платёж!\nUser: {user_id}\nПакет: {payload}\nСумма: {total_stars} ⭐\nCharge ID: {charge_id}"
        )

    else:
        logger.error(f"❌ Неизвестный payload: {payload} | User: {user_id} | Charge ID: {charge_id}")
        await update.message.reply_text(
            "🌑 Что-то пошло не так... Обратись к создателю Зеркала.",
            reply_markup=main_menu_keyboard()
        )

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждаем оплату — обязательно для Stars"""
    query = update.pre_checkout_query
    await query.answer(ok=True)  # Говорим Telegram: всё ок, можно списывать

async def confirm_reading_now(update: Update, context: ContextTypes.DEFAULT_TYPE, reading_type):
    """Начинает генерацию расклада сразу — без подтверждения (если баланс есть)"""
    user_id = update.message.from_user.id
    user_name = user_data[user_id]['name']

    # Сразу тратим 1 расклад
    user_data[user_id]['readings_balance'] -= 1
    user_data[user_id]['total_used'] += 1

    await update.message.reply_text(
        f"Приступаю к ритуалу... Зеркало наполняется туманом... 🔮",
        reply_markup=ReplyKeyboardRemove()
    )

    await update.message.reply_text("🕯️ Карты выбирают тебя... Это займёт 10-20 секунд.")

    custom_question = context.user_data.get('custom_question', None)
    reading = await generate_tarot_reading(
        reading_type=reading_type,
        user_question=custom_question,
        user_name=user_name
    )

    # Сохраняем в историю
    from datetime import datetime
    reading_entry = {
        'type': reading_type,
        'text': reading,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    user_data[user_id]['last_readings'].append(reading_entry)
    if len(user_data[user_id]['last_readings']) > 5:
        user_data[user_id]['last_readings'].pop(0)

    await update.message.reply_text(
        reading,
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет диалог."""
    user_id = update.message.from_user.id
    user_name = user_data[user_id]['name'] if user_id in user_data else "Искатель"
    await update.message.reply_text(
        f'Пусть звёзды освещают твой путь, {user_name}. '
        'Если пожелаешь вновь заглянуть в Зеркало Судеб, просто произнеси /start.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def button_buy_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие кнопки покупки пакета — отправляет инвойс"""
    query = update.callback_query
    await query.answer()

    pack_id = query.data.replace("buy_pack_", "")  # получаем "1", "5", "30"

    if f"pack_{pack_id}" not in PACKAGES:
        await query.edit_message_text("🌑 Неизвестный пакет. Обратись к создателю Зеркала.")
        return

    pack = PACKAGES[f"pack_{pack_id}"]

    # Отправляем инвойс напрямую!
    try:
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=f"🔮 {pack['name']}",
            description=f"Ты получаешь {pack['readings']} раскладов. Магия уже зовёт!",
            payload=f"pack_{pack_id}",  # Идентификатор пакета — пригодится при успешной оплате
            provider_token="",          # ПУСТОЙ для Stars!
            currency="XTR",             # Только Stars для цифровых товаров
            prices=[LabeledPrice(label=pack['name'], amount=pack['price_stars'])],
            start_parameter=f"buy_{pack_id}",
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False,
        )
        await query.edit_message_text("🪄 Инвойс отправлен — нажми кнопку 'Оплатить' ниже!")
    except Exception as e:
        logger.error(f"Ошибка отправки инвойса: {e}")
        await query.edit_message_text("🌑 Не удалось создать инвойс. Попробуй позже.")

# --- Запуск ---
def main():
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
            CONFIRM_READING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reading_confirmation)],
            AWAITING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_question)],
            AWAITING_READING_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reading_type_selection)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    # Обработчики для платежей
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # Обработчик для кнопки "Купить расклады"
    application.add_handler(MessageHandler(filters.Regex('^🛍️ Купить расклады$'), buy_readings))
    application.add_handler(CallbackQueryHandler(button_buy_pack, pattern="^buy_pack_"))
    application.run_polling()

if __name__ == '__main__':
    main()
