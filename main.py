import asyncio
import sqlite3
import time
import re
import os
import aiohttp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
from telegram.error import RetryAfter, TelegramError


# ==================================================
# SETTINGS
# ==================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8702037141:AAHtcXjH97AIxq4JWwU79mB92KUk95Ns5xc")
INSTAGRAM_SESSION_ID = "35351858952:CuMWKOONfJ7OxV:7:AYnSM1cCCL8jLvxWfEKUwjAn8acIV7symRmJTeC51A"

CHECK_INTERVAL = 60
DISPLAY_INTERVAL = 5

DB_FILE = "instagram_monitor.db"


# ==================================================
# HELPER TO EXTRACT USERNAME / URL
# ==================================================

def extract_username(input_text):
    input_text = input_text.strip()
    match = re.search(r"instagram\.com/([a-zA-Z0-9_\.]+)", input_text)
    if match:
        return match.group(1).lower()
    return input_text.lstrip("@").lower()


# ==================================================
# DATABASE
# ==================================================

def get_db():
    return sqlite3.connect(DB_FILE)


def init_database():
    con = get_db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS watches (
            chat_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            state TEXT NOT NULL,
            changed_at INTEGER NOT NULL,
            message_id INTEGER,
            PRIMARY KEY (chat_id, username)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            chat_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            state TEXT NOT NULL,
            changed_at INTEGER NOT NULL,
            PRIMARY KEY (chat_id, username)
        )
    """)

    con.commit()
    con.close()


# ==================================================
# TIME FORMAT
# ==================================================

def format_duration(seconds):
    seconds = int(max(0, seconds))
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60

    if days:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


# ==================================================
# ACCURATE CHECKER
# ==================================================

async def check_instagram(username):
    ds_user_id = INSTAGRAM_SESSION_ID.split(":")[0] if ":" in INSTAGRAM_SESSION_ID else ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1"
    }

    cookies = {
        "sessionid": INSTAGRAM_SESSION_ID.strip(),
        "ds_user_id": ds_user_id
    }

    timeout = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(timeout=timeout, cookies=cookies) as session:
            profile_url = f"https://www.instagram.com/{username}/"
            async with session.get(profile_url, headers=headers, allow_redirects=True) as resp:
                if resp.status in [404, 301, 302] or "accounts/login" in str(resp.url):
                    return "banned"

                html = await resp.text(errors="ignore")

                banned_indicators = [
                    "page not found",
                    "isn't available",
                    "الصفحة غير متوفرة",
                    "sorry, this page isn't available",
                    "the link you followed may be broken",
                    "resticted_profile"
                ]

                if any(indicator in html.lower() for indicator in banned_indicators):
                    return "banned"

                if f'"{username}"' in html.lower() or f'@{username}' in html.lower() or "profilepage_" in html:
                    return "unbanned"

                return "banned"

    except Exception as e:
        print(f"[Checker Error] @{username}: {e}")
        return "unknown"


# ==================================================
# KEYBOARD HELPER
# ==================================================

def get_action_keyboard(username):
    keyboard = [[InlineKeyboardButton("Stop 🖐🏻", callback_data=f"stop_{username}")]]
    return InlineKeyboardMarkup(keyboard)


# ==================================================
# STATUS MESSAGE
# ==================================================

def make_status_message(username, state, changed_at):
    duration = format_duration(time.time() - changed_at)

    if state == "banned":
        return (
            "🔴 <b>BANNED</b>\n\n"
            f"👤 <b>@{username}</b>\n\n"
            "🔴 <b>ACCOUNT STATUS</b>\n"
            "🚫 <b>Account is banned</b>\n\n"
            f"<blockquote>⏱️ <b>Banned for: ”</b>\n"
            f"{duration}</blockquote>\n\n"
            "🔄 <i>Checking every 60 seconds</i>\n\n"
            f"> @{username} is currently <b>BANNED</b>."
        )

    return (
        "🟢 <b>UNBANNED</b>\n\n"
        f"👤 <b>@{username}</b>\n\n"
        "🟢 <b>ACCOUNT STATUS</b>\n"
        "✅ <b>Account is active</b>\n\n"
        f"<blockquote>⏱️ <b>Unbanned for: ”</b>\n"
        f"{duration}</blockquote>\n\n"
        "🔄 <i>Checking every 60 seconds</i>\n\n"
        f"> @{username} is currently <b>UNBANNED</b>."
    )


# ==================================================
# COMMANDS & CALLBACK
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👑 <b>IG BAN & UNBAN CHECKER</b> 👑\n"
        "<b>═══════════════════════</b>\n\n"
        "⚙️ <b>MAKER:</b> @PQQL1\n\n"
        "💎 <i>Advanced 24/7 Instagram Real-Time Status & Counter System</i>\n\n"
        "📌 <b>COMMANDS MENU</b>\n\n"
        "🔹 <code>/watch [username/link]</code>\n"
        "↳ <i>Start live status tracking & timer.</i>\n\n"
        "🔹 <code>/stop [username/link]</code>\n"
        "↳ <i>Stop tracking & remove account.</i>\n\n"
        "🔹 <code>/status [username/link]</code>\n"
        "↳ <i>Check current status & counter.</i>\n\n"
        "🔹 <code>/list</code>\n"
        "↳ <i>List all active monitored targets.</i>\n\n"
        "<b>═══════════════════════</b>\n"
        "💡 <b>Example:</b> <code>/watch instagram</code>"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ <b>Usage:</b> <code>/watch username_or_link</code>", parse_mode="HTML")
        return

    raw_input = context.args[0]
    username = extract_username(raw_input)
    chat_id = update.effective_chat.id

    msg = await update.message.reply_text(f"🔎 <b>Checking profile for @{username}...</b>", parse_mode="HTML")

    state = await check_instagram(username)

    if state == "unknown":
        await msg.edit_text("⚠️ <b>Unable to check account currently. Please try again later.</b>", parse_mode="HTML")
        return

    now = int(time.time())

    con = get_db()
    cur = con.cursor()

    cur.execute("SELECT state, changed_at FROM history WHERE chat_id = ? AND username = ?", (chat_id, username))
    hist_row = cur.fetchone()

    if hist_row:
        old_state, old_changed_at = hist_row
        if old_state == state:
            changed_at = old_changed_at
        else:
            changed_at = now
    else:
        changed_at = now

    cur.execute("""
        INSERT INTO watches (chat_id, username, state, changed_at, message_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, username) DO UPDATE SET
            state = excluded.state,
            changed_at = excluded.changed_at,
            message_id = excluded.message_id
    """, (chat_id, username, state, changed_at, msg.message_id))

    cur.execute("""
        INSERT INTO history (chat_id, username, state, changed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, username) DO UPDATE SET
            state = excluded.state,
            changed_at = excluded.changed_at
    """, (chat_id, username, state, changed_at))

    con.commit()
    con.close()

    await msg.edit_text(
        make_status_message(username, state, changed_at),
        parse_mode="HTML",
        reply_markup=get_action_keyboard(username)
    )


async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id

    if data.startswith("stop_"):
        username = data.replace("stop_", "")

        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT state, changed_at FROM watches WHERE chat_id = ? AND username = ?", (chat_id, username))
        row = cur.fetchone()

        if row:
            state, changed_at = row
            duration = format_duration(time.time() - changed_at)
            status_label = "BANNED" if state == "banned" else "ACTIVE (UNBANNED)"

            cur.execute("DELETE FROM watches WHERE chat_id = ? AND username = ?", (chat_id, username))
            con.commit()

            stop_text = (
                "🛑 <b>MONITORING STOPPED</b>\n\n"
                f"👤 <b>@{username}</b>\n\n"
                f"📌 <b>Last Status:</b> <code>{status_label}</code>\n"
                f"⏱️ <b>Duration Before Stop:</b> <code>{duration}</code>\n\n"
                "<i>The timer continues running in the background and will resume if you watch this account again.</i>"
            )
            await query.edit_message_text(stop_text, parse_mode="HTML")
        else:
            await query.edit_message_text("❌ <b>This account is not currently being monitored.</b>", parse_mode="HTML")

        con.close()


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ <b>Usage:</b> <code>/stop username_or_link</code>", parse_mode="HTML")
        return

    raw_input = context.args[0]
    username = extract_username(raw_input)
    chat_id = update.effective_chat.id

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT state, changed_at FROM watches WHERE chat_id = ? AND username = ?", (chat_id, username))
    row = cur.fetchone()

    if row:
        state, changed_at = row
        duration = format_duration(time.time() - changed_at)
        status_label = "BANNED" if state == "banned" else "ACTIVE (UNBANNED)"

        cur.execute("DELETE FROM watches WHERE chat_id = ? AND username = ?", (chat_id, username))
        con.commit()

        await update.message.reply_text(
            f"🛑 <b>Stopped monitoring @{username}</b>\n"
            f"📌 <b>Last Status:</b> <code>{status_label}</code>\n"
            f"⏱️ <b>Duration:</b> <code>{duration}</code>",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(f"❌ <b>@{username} is not being monitored.</b>", parse_mode="HTML")

    con.close()


async def list_watches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT username, state, changed_at FROM watches WHERE chat_id = ? ORDER BY username", (update.effective_chat.id,))
    rows = cur.fetchall()
    con.close()

    if not rows:
        await update.message.reply_text("📭 <b>No accounts currently being monitored.</b>", parse_mode="HTML")
        return

    text = "📋 <b>MONITORED ACCOUNTS LIST</b>\n\n"
    for username, state, changed_at in rows:
        duration = format_duration(time.time() - changed_at)
        status_text = "🔴 BANNED" if state == "banned" else "🟢 UNBANNED"

        text += f"👤 <b>@{username}</b>\n🔗 https://www.instagram.com/{username}/\nStatus: {status_text}\n⏱️ Duration: <code>{duration}</code>\n\n"

    await update.message.reply_text(text, parse_mode="HTML")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ <b>Usage:</b> <code>/status username_or_link</code>", parse_mode="HTML")
        return

    raw_input = context.args[0]
    username = extract_username(raw_input)

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT state, changed_at FROM watches WHERE chat_id = ? AND username = ?", (update.effective_chat.id, username))
    row = cur.fetchone()
    con.close()

    if not row:
        await update.message.reply_text(f"❌ <b>@{username} is not being monitored.</b>", parse_mode="HTML")
        return

    state, changed_at = row
    await update.message.reply_text(
        make_status_message(username, state, changed_at),
        parse_mode="HTML",
        reply_markup=get_action_keyboard(username)
    )


# ==================================================
# TASKS & MAIN
# ==================================================

async def live_counter(app: Application):
    while True:
        try:
            con = get_db()
            cur = con.cursor()
            cur.execute("SELECT chat_id, username, state, changed_at, message_id FROM watches WHERE message_id IS NOT NULL")
            rows = cur.fetchall()
            con.close()

            for chat_id, username, state, changed_at, message_id in rows:
                try:
                    text = make_status_message(username, state, changed_at)
                    await app.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=get_action_keyboard(username)
                    )
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                except TelegramError:
                    pass
                
                await asyncio.sleep(0.3)

        except Exception:
            pass

        await asyncio.sleep(DISPLAY_INTERVAL)


async def monitor(app: Application):
    while True:
        try:
            con = get_db()
            cur = con.cursor()
            cur.execute("SELECT chat_id, username, state, changed_at, message_id FROM watches")
            accounts = cur.fetchall()
            con.close()

            for chat_id, username, old_state, changed_at, message_id in accounts:
                new_state = await check_instagram(username)

                if new_state == "unknown" or new_state == old_state:
                    continue

                now = int(time.time())
                previous_duration = format_duration(now - changed_at)

                if old_state == "unbanned" and new_state == "banned":
                    info_msg = (
                        f"⚠️ <b>STATUS CHANGE DETECTED!</b>\n\n"
                        f"👤 Account: <b>@{username}</b>\n"
                        f"⏳ Was <b>UNBANNED (ACTIVE)</b> for:\n"
                        f"<code>{previous_duration}</code>\n\n"
                        f"🚨 <b>ACCOUNT IS NOW BANNED!</b>"
                    )
                else:
                    info_msg = (
                        f"🎉 <b>STATUS CHANGE DETECTED!</b>\n\n"
                        f"👤 Account: <b>@{username}</b>\n"
                        f"⏳ Was <b>BANNED</b> for:\n"
                        f"<code>{previous_duration}</code>\n\n"
                        f"✅ <b>ACCOUNT IS NOW UNBANNED!</b>"
                    )

                try:
                    await app.bot.send_message(chat_id=chat_id, text=info_msg, parse_mode="HTML")
                except Exception:
                    pass

                new_status_text = make_status_message(username, new_state, now)
                new_message_id = None
                
                try:
                    sent_msg = await app.bot.send_message(
                        chat_id=chat_id,
                        text=new_status_text,
                        parse_mode="HTML",
                        reply_markup=get_action_keyboard(username)
                    )
                    new_message_id = sent_msg.message_id
                except Exception:
                    pass

                con = get_db()
                cur = con.cursor()
                cur.execute(
                    "UPDATE watches SET state = ?, changed_at = ?, message_id = ? WHERE chat_id = ? AND username = ?",
                    (new_state, now, new_message_id, chat_id, username)
                )
                cur.execute("""
                    INSERT INTO history (chat_id, username, state, changed_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(chat_id, username) DO UPDATE SET
                        state = excluded.state,
                        changed_at = excluded.changed_at
                """, (chat_id, username, new_state, now))

                con.commit()
                con.close()

                await asyncio.sleep(2)

        except Exception:
            pass

        await asyncio.sleep(CHECK_INTERVAL)


async def on_startup(app: Application):
    asyncio.create_task(monitor(app))
    asyncio.create_task(live_counter(app))


def main():
    init_database()
    # بناء التطبيق بالطريقة الصحيحة الآمنة
    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("list", list_watches))
    app.add_handler(CommandHandler("status", status))
    
    app.add_handler(CallbackQueryHandler(button_click_handler))

    print("البوت يعمل بنجاح على Render...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()