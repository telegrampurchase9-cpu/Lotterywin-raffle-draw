import os
import sqlite3
import logging
import secrets
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
DB_PATH = os.environ.get('RAFFLE_DB_PATH', 'raffle.db')
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS entries (round INTEGER NOT NULL, user_id INTEGER NOT NULL, username TEXT, full_name TEXT, entered_at TEXT NOT NULL, PRIMARY KEY(round, user_id))')
    conn.execute('CREATE TABLE IF NOT EXISTS rounds (round INTEGER PRIMARY KEY, open INTEGER NOT NULL DEFAULT 0, message_id INTEGER, chat_id INTEGER)')
    conn.commit()
    return conn


def get_chat_id():
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='chat_id'").fetchone()
        return int(row[0]) if row else None


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat_id = get_chat_id()
    if not user or not chat_id:
        return False
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        return member.status in ('creator', 'administrator')
    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        '🎟️ Welcome to Lotterywin Raffle Bot!\n\n'
        'Group admins: add me to your raffle group, promote me to admin, then run /setchat in that group.\n'
        'Commands: /help'
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        '🎟️ LOTTER YWIN RAFFLE BOT — COMMANDS\n\n'
        'Group admin setup: /setchat (run in the group)\n'
        'Open round 1: /open1\nOpen round 2: /open2\n'
        'Close round 1: /close1\nClose round 2: /close2\n'
        'Draw 5 winners for round 1: /draw1\nDraw 5 winners for round 2: /draw2\n'
        'Check entries: /entries1 or /entries2\n'
        'Only admins of the configured group can manage rounds. Each person can enter each round once.'
    )


async def setchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ('group', 'supergroup'):
        await update.effective_message.reply_text('Please run /setchat inside the group where the raffle will take place.')
        return
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if member.status not in ('creator', 'administrator'):
        await update.effective_message.reply_text('Only a group admin can set up the raffle group.')
        return
    bot_member = await context.bot.get_chat_member(update.effective_chat.id, context.bot.id)
    if bot_member.status not in ('creator', 'administrator'):
        await update.effective_message.reply_text('Please promote me to group admin first, then run /setchat again.')
        return
    with db() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES('chat_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(update.effective_chat.id),))
    await update.effective_message.reply_text('✅ This group is now configured for Lotterywin raffles.')


async def open_round(update: Update, context: ContextTypes.DEFAULT_TYPE, round_no: int):
    if not await is_admin(update, context):
        await update.effective_message.reply_text('Only admins of the configured raffle group can do that.')
        return
    chat_id = get_chat_id()
    with db() as conn:
        conn.execute('INSERT INTO rounds(round,open,chat_id) VALUES(?,1,?) ON CONFLICT(round) DO UPDATE SET open=1, chat_id=excluded.chat_id, message_id=NULL', (round_no, chat_id))
        conn.execute('DELETE FROM entries WHERE round=?', (round_no,))
    times = {1: '2:00 PM', 2: '5:30 PM'}
    text = (f'🎟️ LOTTER YWIN RAFFLE — ROUND {round_no}\n\n'
            f'💰 Prize: ₦20,000 per winner\n🏆 Winners in this round: 5\n'
            f'🕒 Scheduled round time: {times[round_no]}\n\n'
            'Tap below to enter. One entry per person for this round. Winners will be selected when an admin runs the draw.')
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton('🎟️ Enter raffle', callback_data=f'enter:{round_no}')]])
    msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    with db() as conn:
        conn.execute('UPDATE rounds SET message_id=? WHERE round=?', (msg.message_id, round_no))


async def open1(update: Update, context: ContextTypes.DEFAULT_TYPE): await open_round(update, context, 1)
async def open2(update: Update, context: ContextTypes.DEFAULT_TYPE): await open_round(update, context, 2)


async def enter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, round_text = query.data.split(':', 1)
        round_no = int(round_text)
    except Exception:
        await query.answer('Invalid raffle.', show_alert=True); return
    chat_id = get_chat_id()
    with db() as conn:
        row = conn.execute('SELECT open FROM rounds WHERE round=?', (round_no,)).fetchone()
        if not row or row[0] != 1 or query.message.chat_id != chat_id:
            await query.answer('This raffle is not open right now.', show_alert=True); return
        user = query.from_user
        try:
            conn.execute('INSERT INTO entries(round,user_id,username,full_name,entered_at) VALUES(?,?,?,?,?)',
                         (round_no, user.id, user.username, user.full_name, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            await query.answer('You are entered! Good luck 🎉', show_alert=True)
        except sqlite3.IntegrityError:
            await query.answer('You have already entered this round.', show_alert=True)


async def close_round(update: Update, context: ContextTypes.DEFAULT_TYPE, round_no: int):
    if not await is_admin(update, context):
        await update.effective_message.reply_text('Only admins of the configured raffle group can do that.'); return
    with db() as conn:
        conn.execute('UPDATE rounds SET open=0 WHERE round=?', (round_no,))
    await update.effective_message.reply_text(f'🔒 Round {round_no} is now closed to new entries.')

async def close1(update: Update, context: ContextTypes.DEFAULT_TYPE): await close_round(update, context, 1)
async def close2(update: Update, context: ContextTypes.DEFAULT_TYPE): await close_round(update, context, 2)


async def draw_round(update: Update, context: ContextTypes.DEFAULT_TYPE, round_no: int):
    if not await is_admin(update, context):
        await update.effective_message.reply_text('Only admins of the configured raffle group can draw winners.'); return
    chat_id = get_chat_id()
    with db() as conn:
        conn.execute('UPDATE rounds SET open=0 WHERE round=?', (round_no,))
        rows = conn.execute('SELECT user_id, username, full_name FROM entries WHERE round=?', (round_no,)).fetchall()
    if not rows:
        await update.effective_message.reply_text(f'Round {round_no} has no entries, so no winners were drawn.'); return
    winners = secrets.SystemRandom().sample(rows, min(5, len(rows)))
    lines = [f'🎉 LOTTERYWIN RAFFLE — ROUND {round_no} RESULTS 🎉', '', '💰 Prize: ₦20,000 each', '🏆 Winners:']
    for i, (user_id, username, full_name) in enumerate(winners, 1):
        display = f'@{username}' if username else full_name
        lines.append(f'{i}. {display} (ID: {user_id})')
    lines += ['', f'Total entries: {len(rows)}', 'Admin: please verify winners and arrange prize payment.']
    await context.bot.send_message(chat_id=chat_id, text='\n'.join(lines))

async def draw1(update: Update, context: ContextTypes.DEFAULT_TYPE): await draw_round(update, context, 1)
async def draw2(update: Update, context: ContextTypes.DEFAULT_TYPE): await draw_round(update, context, 2)


async def entries(update: Update, context: ContextTypes.DEFAULT_TYPE, round_no: int):
    if not await is_admin(update, context):
        await update.effective_message.reply_text('Only admins of the configured raffle group can check entries.'); return
    with db() as conn:
        count = conn.execute('SELECT COUNT(*) FROM entries WHERE round=?', (round_no,)).fetchone()[0]
    await update.effective_message.reply_text(f'Round {round_no}: {count} unique entr{ "y" if count == 1 else "ies" }.')
async def entries1(update: Update, context: ContextTypes.DEFAULT_TYPE): await entries(update, context, 1)
async def entries2(update: Update, context: ContextTypes.DEFAULT_TYPE): await entries(update, context, 2)


def main():
    if not TOKEN:
        raise SystemExit('Set TELEGRAM_BOT_TOKEN environment variable before running the bot.')
    db().close()
    app = Application.builder().token(TOKEN).build()
    for command, handler in [
        ('start', start), ('help', help_cmd), ('setchat', setchat),
        ('open1', open1), ('open2', open2), ('close1', close1), ('close2', close2),
        ('draw1', draw1), ('draw2', draw2), ('entries1', entries1), ('entries2', entries2),
    ]:
        app.add_handler(CommandHandler(command, handler))
    app.add_handler(CallbackQueryHandler(enter_callback, pattern=r'^enter:[12]$'))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
