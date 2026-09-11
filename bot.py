import os
import json
import glob
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# BOT_TOKEN is read from the environment. Never hardcode it here.
# On a VPS: export BOT_TOKEN="your_token_here"
# On Render/Railway: set it as an Environment Variable in the dashboard.
BOT_TOKEN = os.environ.get("BOT_TOKEN")

QUIZ_DIR = os.path.join("quiz_data", "quizzes")
os.makedirs(QUIZ_DIR, exist_ok=True)

SIGNATURE = "◄❥‌‌⃟⃝♛❤️‍🔥 ⃪ͥ͢ ᷟ•ᥫ᭡𝐀⃯⃖𝐑⃯⃖𝐘⃯⃖𝐀⃯⃖𝐍➤"

MIN_OPTIONS = 2
MAX_OPTIONS = 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def list_quiz_files():
    return sorted(glob.glob(os.path.join(QUIZ_DIR, "*.json")))


def quiz_display_name(path):
    name = os.path.basename(path)
    if name.endswith(".json"):
        name = name[:-5]
    return name


def validate_quiz(data):
    """Returns (is_valid, error_message_or_None)."""
    if not isinstance(data, list):
        return False, "JSON root ek array (list) hona chahiye."
    if len(data) == 0:
        return False, "Quiz me kam se kam ek question hona chahiye."

    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            return False, f"Item #{i}: object hona chahiye."

        if "question" not in item or not isinstance(item["question"], str) or not item["question"].strip():
            return False, f"Item #{i}: 'question' field missing ya khali hai."

        if "options" not in item or not isinstance(item["options"], list):
            return False, f"Item #{i}: 'options' field missing ya list nahi hai."

        options = item["options"]
        if not (MIN_OPTIONS <= len(options) <= MAX_OPTIONS):
            return False, (
                f"Item #{i}: 'options' me {MIN_OPTIONS} se {MAX_OPTIONS} options hone "
                f"chahiye (mila: {len(options)})."
            )
        for j, opt in enumerate(options, start=1):
            if not isinstance(opt, str) or not opt.strip():
                return False, f"Item #{i}: option #{j} khali ya string nahi hai."

        if "correct" not in item or not isinstance(item["correct"], int) or isinstance(item["correct"], bool):
            return False, f"Item #{i}: 'correct' field missing ya integer nahi hai."
        if not (0 <= item["correct"] < len(options)):
            return False, f"Item #{i}: 'correct' index options ki range ke bahar hai."

        if "explanation" in item and not isinstance(item["explanation"], str):
            return False, f"Item #{i}: 'explanation' string honi chahiye."

    return True, None


def unique_filename(base_name: str) -> str:
    safe = "".join(c for c in base_name if c.isalnum() or c in ("-", "_", " ")).strip()
    safe = safe.replace(" ", "_")
    if not safe:
        safe = "quiz"
    if not safe.endswith(".json"):
        safe += ".json"

    candidate = safe
    counter = 1
    while os.path.exists(os.path.join(QUIZ_DIR, candidate)):
        stem = safe[:-5]
        candidate = f"{stem}_{counter}.json"
        counter += 1
    return candidate


def question_text(item):
    return f"{item['question']}\n\n{SIGNATURE}"


def build_question_keyboard(options, q_index):
    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"ans|{q_index}|{i}")]
        for i, opt in enumerate(options)
    ]
    keyboard.append([InlineKeyboardButton("🛑 STOP", callback_data="stop")])
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    files = list_quiz_files()
    if not files:
        await update.message.reply_text(
            "👋 Welcome! Abhi koi quiz available nahi hai.\n\n"
            "Ek valid quiz JSON file bhejo, main use save kar dunga.\n"
            "Format janne ke liye /help bhejo."
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"📘 {quiz_display_name(f)}", callback_data=f"startquiz|{os.path.basename(f)}")]
        for f in files
    ]
    await update.message.reply_text(
        "👋 Welcome! Neeche available quizzes hain, kisi ek par tap karo shuru karne ke liye:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Quiz Bot Help*\n\n"
        "/start - Available quizzes ki list dekho\n"
        "/cancel - Chal rahi quiz ko rokho\n"
        "/help - Yeh help message\n\n"
        "📤 *Naya quiz add karna:*\n"
        "Bas ek valid JSON file bhej do, format:\n"
        "```\n"
        "[\n"
        "  {\n"
        '    "question": "Question?",\n'
        '    "options": ["Option 1", "Option 2", "Option 3", "Option 4"],\n'
        '    "correct": 0,\n'
        '    "explanation": "Explanation"\n'
        "  }\n"
        "]\n"
        "```\n"
        "- 2, 3 ya 4 options allowed\n"
        "- 'correct' 0-based index hota hai (pehla option = 0)"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("quiz_items"):
        context.user_data.clear()
        await update.message.reply_text("🛑 Quiz cancel kar di gayi.")
    else:
        await update.message.reply_text("Koi active quiz nahi chal rahi.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    filename = doc.file_name or ""

    if not filename.lower().endswith(".json"):
        await update.message.reply_text("❌ Sirf .json file bhejo.")
        return

    tg_file = await doc.get_file()
    raw = await tg_file.download_as_bytearray()

    try:
        data = json.loads(bytes(raw).decode("utf-8"))
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid JSON: {e}")
        return

    is_valid, error = validate_quiz(data)
    if not is_valid:
        await update.message.reply_text(f"❌ Quiz JSON invalid hai:\n{error}")
        return

    save_name = unique_filename(os.path.splitext(filename)[0])
    save_path = os.path.join(QUIZ_DIR, save_name)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    await update.message.reply_text(
        f"✅ Quiz saved: {save_name}\n"
        f"📊 Questions: {len(data)}\n\n"
        "Ab /start karke isse khel sakte ho."
    )


# ---------------------------------------------------------------------------
# Quiz flow (all via inline button callbacks)
# ---------------------------------------------------------------------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("startquiz|"):
        filename = data.split("|", 1)[1]
        await start_quiz(query, context, filename)
    elif data.startswith("ans|"):
        _, q_index_str, opt_index_str = data.split("|")
        await handle_answer(query, context, int(q_index_str), int(opt_index_str))
    elif data == "next":
        await send_question(query, context)
    elif data == "stop":
        await stop_quiz(query, context)
    elif data == "playagain":
        filename = context.user_data.get("quiz_file")
        if filename:
            await start_quiz(query, context, filename)
        else:
            await query.edit_message_text("Quiz file nahi mili. /start karke naya quiz chuno.")


async def start_quiz(query, context, filename):
    path = os.path.join(QUIZ_DIR, filename)
    if not os.path.exists(path):
        await query.edit_message_text("❌ Quiz file nahi mili. Shayad delete ho gayi ho.")
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        await query.edit_message_text("❌ Quiz file load karne me error aayi.")
        return

    is_valid, error = validate_quiz(data)
    if not is_valid:
        await query.edit_message_text(f"❌ Saved quiz corrupt hai: {error}")
        return

    context.user_data["quiz_file"] = filename
    context.user_data["quiz_items"] = data
    context.user_data["q_index"] = 0
    context.user_data["score"] = 0
    context.user_data["total"] = len(data)

    await send_question(query, context)


async def send_question(query, context):
    items = context.user_data.get("quiz_items")
    idx = context.user_data.get("q_index", 0)

    if items is None:
        await query.edit_message_text("Koi active quiz nahi hai. /start karo.")
        return

    if idx >= len(items):
        await finish_quiz(query, context)
        return

    item = items[idx]
    text = question_text(item)
    keyboard = build_question_keyboard(item["options"], idx)
    await query.edit_message_text(text, reply_markup=keyboard)


async def handle_answer(query, context, q_index, opt_index):
    items = context.user_data.get("quiz_items")
    current_idx = context.user_data.get("q_index")

    if items is None or current_idx is None or q_index != current_idx:
        await query.answer("Yeh question ab active nahi hai.", show_alert=True)
        return

    item = items[q_index]
    correct_index = item["correct"]
    is_correct = opt_index == correct_index

    if is_correct:
        context.user_data["score"] = context.user_data.get("score", 0) + 1
        result_line = "✅ Sahi jawab!"
    else:
        correct_text = item["options"][correct_index]
        result_line = f"❌ Galat jawab! Sahi jawab: {correct_text}"

    explanation = item.get("explanation", "")
    parts = [result_line]
    if explanation:
        parts.append(f"\n💡 {explanation}")
    parts.append(f"\n{SIGNATURE}")
    text = "\n".join(parts)

    context.user_data["q_index"] = q_index + 1

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ NEXT", callback_data="next")],
        [InlineKeyboardButton("🛑 STOP", callback_data="stop")],
    ])
    await query.edit_message_text(text, reply_markup=keyboard)


async def finish_quiz(query, context):
    score = context.user_data.get("score", 0)
    total = context.user_data.get("total", 0)
    percentage = (score / total * 100) if total else 0

    text = (
        "🏁 Quiz Complete!\n\n"
        f"✅ Score: {score}/{total}\n"
        f"📊 Percentage: {percentage:.1f}%\n\n"
        f"{SIGNATURE}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 PLAY AGAIN", callback_data="playagain")],
    ])
    await query.edit_message_text(text, reply_markup=keyboard)


async def stop_quiz(query, context):
    score = context.user_data.get("score", 0)
    answered = context.user_data.get("q_index", 0)
    context.user_data.clear()

    text = (
        f"🛑 Quiz roki gayi.\n"
        f"Aapne {answered} questions try kiye, score: {score}.\n\n"
        "/start karke naya quiz chuno."
    )
    await query.edit_message_text(text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable set nahi hai. "
            "Isse set karo (export BOT_TOKEN=...) phir bot run karo."
        )

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot starting (polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
