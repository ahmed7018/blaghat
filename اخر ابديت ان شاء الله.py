import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import sqlite3
from datetime import datetime


TOKEN = "7653244288:AAE4WNxbp10NOB3S3Vvnh10v0dkcsu0K7DY"
ADMIN_IDS = [1797640202]  
REPORT_GROUP_ID = -1002395481383  


REPORT_REASONS = {
    "dislike": "لم تعجبني",
    "child_abuse": "إساءة للأطفال",
    "violence": "عنف",
    "illegal_goods": "بضائع غير قانونية",
    "adult_content": "محتوى غير قانوني للبالغين",
    "personal_data": "معلومات شخصية",
    "terrorism": "إرهاب",
    "scam": "احتيال أو إزعاج",
    "copyright": "حقوق النشر",
    "other_illegal": "أخرى",
    "should_be_removed": "ليست (غير قانونية)، ولكن يجب إزالتها"
}


def init_db():
    conn = sqlite3.connect('reports.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS reports
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  reporter_id INTEGER NOT NULL,
                  reported_user_id INTEGER NOT NULL,
                  reported_username TEXT,
                  message_text TEXT,
                  chat_id INTEGER NOT NULL,
                  message_id INTEGER NOT NULL,
                  reason TEXT NOT NULL,
                  details TEXT,
                  media_type TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                  status TEXT DEFAULT 'pending',
                  admin_action TEXT,
                  action_timestamp DATETIME,
                  group_message_id INTEGER)''') 
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT NOT NULL,
                  last_name TEXT,
                  status TEXT DEFAULT 'pending',
                  join_date DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()

init_db()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        await show_admin_panel(update)
    else:
        await update.message.reply_text(
            f"مرحباً {user.first_name}!\n"
            "لإرسال بلاغ، اضغط على زر '⛔ الإبلاغ' تحت الرسالة المخالفة."
        )

async def show_admin_panel(update: Update):
    keyboard = [
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📨 إدارة البلاغات", callback_data="admin_reports")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛠️ لوحة تحكم الأدمن:", reply_markup=reply_markup)

async def add_report_button(application, message):
    keyboard = [[InlineKeyboardButton("⛔ الإبلاغ", callback_data=f"report_{message.id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في إضافة زر الإبلاغ: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.chat.type in ['group', 'supergroup']:
        await add_report_button(context.application, update.message)

async def handle_report_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("report_"):
        return

    message_id = int(query.data.split('_')[1])
    reported_message = query.message

    context.user_data['report_data'] = {
        'reported_user_id': reported_message.from_user.id,
        'reported_username': reported_message.from_user.username or reported_message.from_user.first_name,
        'message_text': reported_message.text or "محتوى غير نصي",
        'chat_id': reported_message.chat.id,
        'message_id': reported_message.id,
        'media_type': get_media_type(reported_message)
    }

    keyboard = [[InlineKeyboardButton(reason, callback_data=f"reason_{key}")] 
                for key, reason in REPORT_REASONS.items()]
    
    await query.edit_message_text(
        text=f"جارٍ الإبلاغ عن رسالة من {context.user_data['report_data']['reported_username']}\n"
             "اختر سبب الإبلاغ:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def get_media_type(message):
    if message.photo: return "photo"
    elif message.video: return "video"
    elif message.document: return "document"
    elif message.audio: return "audio"
    return None

async def handle_report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    reason_key = query.data.split('_')[1]
    reason_text = REPORT_REASONS.get(reason_key, "سبب غير محدد")
    
    report_data = context.user_data.get('report_data', {})
    if not report_data:
        await query.edit_message_text("❌ خطأ في معالجة البلاغ")
        return

    if reason_key in ["other_illegal", "should_be_removed"]:
        await query.edit_message_text(
            text="أرسل تفاصيل إضافية عن المخالفة:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="cancel_report")]])
        )
        context.user_data['awaiting_details'] = True
        context.user_data['selected_reason'] = reason_text
        return

    await process_report(context, query.from_user, report_data, reason_text)

async def process_report(context: ContextTypes.DEFAULT_TYPE, reporter, report_data, reason, details=None):
    conn = sqlite3.connect('reports.db')
    c = conn.cursor()
    
    c.execute('''INSERT INTO reports 
                 (reporter_id, reported_user_id, reported_username, message_text, 
                  chat_id, message_id, reason, details, media_type)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (reporter.id, 
               report_data['reported_user_id'],
               report_data['reported_username'],
               report_data['message_text'],
               report_data['chat_id'],
               report_data['message_id'],
               reason,
               details,
               report_data['media_type']))
    
    report_id = c.lastrowid
    conn.commit()
    conn.close()

    group_message = await notify_report(context, report_data, reason, reporter, details)
    
    if group_message:
        conn = sqlite3.connect('reports.db')
        c = conn.cursor()
        c.execute('UPDATE reports SET group_message_id=? WHERE id=?', 
                 (group_message.message_id, report_id))
        conn.commit()
        conn.close()

    await context.bot.send_message(
        reporter.id,
        f"✅ تم استلام بلاغك بنجاح!\nالسبب: {reason}"
    )

async def notify_report(context: ContextTypes.DEFAULT_TYPE, report_data: dict, reason: str, reporter, details: str = None):
    message = generate_report_message(report_data, reason, reporter, details)
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, message)
        except Exception as e:
            logger.error(f"فشل إرسال للأدمن {admin_id}: {e}")

    try:
        group_message = await context.bot.send_message(
            REPORT_GROUP_ID,
            message,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("تمت المعالجة", callback_data=f"resolve_{report_data['message_id']}")]
            ])
        )
        return group_message
    except Exception as e:
        logger.error(f"فشل إرسال للجروب: {e}")
        return None

def generate_report_message(report_data, reason, reporter, details):
    msg = (
        f"🚨 بلاغ جديد #{report_data['message_id']}\n\n"
        f"👤 مقدم البلاغ: {reporter.first_name} (@{reporter.username or 'لا يوجد'})\n"
        f"🆔 الأيدي: {reporter.id}\n"
        f"👤 المستهدف: {report_data['reported_username']}\n"
        f"🆔 الأيدي: {report_data['reported_user_id']}\n"
        f"📌 السبب: {reason}\n"
    )
    
    if details:
        msg += f"📝 التفاصيل: {details}\n\n"
    
    msg += (
        f"📄 المحتوى: {report_data['message_text']}\n\n"
        f"🔗 الرابط: t.me/c/{str(report_data['chat_id']).replace('-100', '')}/{report_data['message_id']}\n"
        f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return msg

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("resolve_"):
        message_id = int(query.data.split('_')[1])
        await resolve_report(context, query, message_id)

async def resolve_report(context: ContextTypes.DEFAULT_TYPE, query, message_id):
    conn = sqlite3.connect('reports.db')
    c = conn.cursor()
    
    c.execute('''UPDATE reports SET 
                 status="resolved",
                 admin_action="تمت المعالجة",
                 action_timestamp=CURRENT_TIMESTAMP
                 WHERE message_id=?''', (message_id,))
    
    c.execute('SELECT group_message_id FROM reports WHERE message_id=?', (message_id,))
    group_msg_id = c.fetchone()[0]
    
    conn.commit()
    conn.close()

    if group_msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=REPORT_GROUP_ID,
                message_id=group_msg_id,
                text=f"{query.message.text}\n\n✅ تمت المعالجة بواسطة {query.from_user.first_name}"
            )
        except Exception as e:
            logger.error(f"فشل تحديث رسالة الجروب: {e}")

    await query.edit_message_text("✅ تمت معالجة البلاغ")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_details', False):
        details = update.message.text
        reason = context.user_data['selected_reason']
        report_data = context.user_data['report_data']
        
        await process_report(context, update.message.from_user, report_data, reason, details)
        
        context.user_data.pop('awaiting_details', None)
        context.user_data.pop('selected_reason', None)
        context.user_data.pop('report_data', None)

async def cancel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تم إلغاء عملية الإبلاغ")
    context.user_data.clear()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("حدث خطأ:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("❌ حدث خطأ، يرجى المحاولة لاحقاً")

def main():
    application = Application.builder().token(TOKEN).build()

    handlers = [
        CommandHandler("start", start),
        MessageHandler(filters.ALL & ~filters.COMMAND, handle_message),
        CallbackQueryHandler(handle_report_button, pattern='^report_'),
        CallbackQueryHandler(handle_report_reason, pattern='^reason_'),
        CallbackQueryHandler(cancel_report, pattern='^cancel_report'),
        CallbackQueryHandler(handle_admin_actions, pattern='^(resolve_|admin_)'),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    ]
    
    for handler in handlers:
        application.add_handler(handler)
    
    application.add_error_handler(error_handler)
    application.run_polling()

if __name__ == '__main__':
    main()