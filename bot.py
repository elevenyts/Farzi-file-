import os
import json
import glob
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PollAnswerHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Prefer setting BOT_TOKEN as an environment variable when your host supports it.
# If your host doesn't support environment variables (e.g. it only lets you
# upload a script file), paste your token directly into the string below.
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8902002616:AAFBgAgzeuzTYBhm0AP7NZNnVDx97afvLIs"

QUIZ_DIR = os.path.join("quiz_data", "quizzes")
os.makedirs(QUIZ_DIR, exist_ok=True)

SIGNATURE = "◄❥‌‌⃟⃝♛❤️‍🔥 ⃪ͥ͢ ᷟ•ᥫ᭡𝐀⃯⃖𝐑⃯⃖𝐘⃯⃖𝐀⃯⃖𝐍➤"

MIN_OPTIONS = 2
MAX_OPTIONS = 4

# How long each poll stays open before the bot auto-sends the next question.
QUESTION_SECONDS = int(os.environ.get("QUESTION_SECONDS", "15"))

POLL_QUESTION_MAX = 300
POLL_OPTION_MAX = 100
POLL_EXPLANATION_MAX = 200


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


def build_poll_question(item):
    """Question text + signature, safely trimmed to Telegram's poll question limit.
    No numbering (Q1/1/50 etc.) is ever added here."""
    text = f"{item['question']}\n\n{SIGNATURE}"
    if len(text) <= POLL_QUESTION_MAX:
        return text
    # Trim the question part only, keep the full signature intact.
    overflow = len(text) - POLL_QUESTION_MAX
    trimmed_question = item["question"][: max(0, len(item["question"]) - overflow - 1)] + "…"
    return f"{trimmed_question}\n\n{SIGNATURE}"


def build_poll_options(item):
    return [opt[:POLL_OPTION_MAX] for opt in item["options"]]


def build_poll_explanation(item):
    explanation = item.get("explanation", "").strip()
    if not explanation:
        return None
    return explanation[:POLL_EXPLANATION_MAX]


def job_name_for(chat_id):
    return f"advance_{chat_id}"


def cancel_advance_job(context: ContextTypes.DEFAULT_TYPE, chat_id):
    if context.job_queue is None:
        return
    for job in context.job_queue.get_jobs_by_name(job_name_for(chat_id)):
        job.schedule_removal()


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel_advance_job(context, update.effective_chat.id)
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
        "- 'correct' 0-based index hota hai (pehla option = 0)\n\n"
        f"⏱ Har question {QUESTION_SECONDS} second ke liye open rehta hai, phir agla apne aap aa jata hai."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if context.user_data.get("quiz_items"):
        cancel_advance_job(context, chat_id)
        score = context.user_data.get("score", 0)
        context.user_data.clear()
        await update.message.reply_text(f"🛑 Quiz cancel kar di gayi.\nScore: {score}")
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
# Quiz flow (native Telegram Quiz Polls)
# ---------------------------------------------------------------------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data.startswith("startquiz|"):
        filename = data.split("|", 1)[1]
        await start_quiz(chat_id, context, filename, stop_query=query)
    elif data == "stop":
        await stop_quiz(query, context)
    elif data == "playagain":
        filename = context.user_data.get("quiz_file")
        if filename:
            await start_quiz(chat_id, context, filename, stop_query=query)
        else:
            await query.edit_message_text("Quiz file nahi mili. /start karke naya quiz chuno.")


async def start_quiz(chat_id, context, filename, stop_query=None):
    path = os.path.join(QUIZ_DIR, filename)
    if not os.path.exists(path):
        text = "❌ Quiz file nahi mili. Shayad delete ho gayi ho."
        if stop_query:
            await stop_query.edit_message_text(text)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text)
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text="❌ Quiz file load karne me error aayi.")
        return

    is_valid, error = validate_quiz(data)
    if not is_valid:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Saved quiz corrupt hai: {error}")
        return

    cancel_advance_job(context, chat_id)
    context.user_data["quiz_file"] = filename
    context.user_data["quiz_items"] = data
    context.user_data["q_index"] = 0
    context.user_data["score"] = 0
    context.user_data["total"] = len(data)
    context.user_data["poll_id"] = None

    stop_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP", callback_data="stop")]])
    stop_text = (
        f"🎯 Quiz shuru! {len(data)} sawaal aayenge, har ek {QUESTION_SECONDS} second ke liye khula rahega.\n"
        "Kabhi bhi rokne ke liye neeche 🛑 STOP dabao."
    )
    if stop_query:
        await stop_query.edit_message_text(stop_text, reply_markup=stop_keyboard)
    else:
        await context.bot.send_message(chat_id=chat_id, text=stop_text, reply_markup=stop_keyboard)

    await send_question(chat_id, context)


async def send_question(chat_id, context: ContextTypes.DEFAULT_TYPE):
    items = context.user_data.get("quiz_items")
    idx = context.user_data.get("q_index", 0)

    if not items:
        return

    if idx >= len(items):
        await finish_quiz(chat_id, context)
        return

    item = items[idx]
    question_text = build_poll_question(item)
    options = build_poll_options(item)
    correct_index = item["correct"]
    explanation = build_poll_explanation(item)

    msg = await context.bot.send_poll(
        chat_id=chat_id,
        question=question_text,
        options=options,
        type="quiz",
        correct_option_id=correct_index,
        is_anonymous=False,
        explanation=explanation,
        open_period=QUESTION_SECONDS,
    )

    context.user_data["poll_id"] = msg.poll.id
    context.user_data["correct_index"] = correct_index

    if context.job_queue is None:
        logger.warning("JobQueue not available — auto-advance won't work. Install python-telegram-bot[job-queue].")
        return

    context.job_queue.run_once(
        advance_after_timer,
        when=QUESTION_SECONDS,
        data={"poll_id": msg.poll.id},
        name=job_name_for(chat_id),
        chat_id=chat_id,
        user_id=chat_id,
    )


async def advance_after_timer(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if context.user_data.get("poll_id") != job.data.get("poll_id"):
        return  # user already stopped or moved on
    context.user_data["q_index"] = context.user_data.get("q_index", 0) + 1
    await send_question(job.chat_id, context)


async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    if context.user_data.get("poll_id") != answer.poll_id:
        return
    if not answer.option_ids:
        return  # vote retracted
    chosen = answer.option_ids[0]
    correct = context.user_data.get("correct_index")
    if chosen == correct:
        context.user_data["score"] = context.user_data.get("score", 0) + 1


async def finish_quiz(chat_id, context: ContextTypes.DEFAULT_TYPE):
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
    context.user_data["poll_id"] = None
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


async def stop_quiz(query, context: ContextTypes.DEFAULT_TYPE):
    chat_id = query.message.chat_id
    cancel_advance_job(context, chat_id)
    score = context.user_data.get("score", 0)
    answered_upto = context.user_data.get("q_index", 0)
    context.user_data.clear()

    text = (
        f"🛑 Quiz roki gayi.\n"
        f"Aapne {answered_upto} questions try kiye, score: {score}.\n\n"
        "/start karke naya quiz chuno."
    )
    await query.edit_message_text(text)


# ---------------------------------------------------------------------------
# Dummy HTTP server (Render free Web Service needs an open port for its
# health check; the bot itself only uses Telegram long-polling, not HTTP)
# ---------------------------------------------------------------------------

class _HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        # Silence default request logging so it doesn't spam bot logs
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    logger.info(f"Health check server listening on port {port}")
    server.serve_forever()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable set nahi hai. "
            "Isse set karo (export BOT_TOKEN=...) phir bot run karo."
        )

    # Start the dummy HTTP server in a background thread so Render's port
    # check passes, while the bot itself keeps polling Telegram.
    threading.Thread(target=start_health_server, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()

    if application.job_queue is None:
        raise RuntimeError(
            "JobQueue install nahi hai. requirements.txt me "
            "'python-telegram-bot[job-queue]>=22.0,<23.0' hona chahiye, "
            "phir 'pip install -r requirements.txt' dobara chalao."
        )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(PollAnswerHandler(poll_answer_handler))

    logger.info("Bot starting (polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
