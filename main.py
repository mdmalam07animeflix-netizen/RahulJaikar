# main.py
import os
import asyncio
import threading
from datetime import datetime, timedelta
from pyrogram import Client, filters, types
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from flask import Flask

# === CONFIG FROM RENDER ===
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MONGO_URI = os.getenv("MONGO_URI")

app = Client("anime_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
db = AsyncIOMotorClient(MONGO_URI).anime_db

# === COLLECTIONS ===
anime_col = db.anime
users_col = db.users
pending_sub = db.pending_subscriptions
config_col = db.bot_config

# === CONFIG GETTER ===
async def get_config():
    cfg = await config_col.find_one({"_id": "config"})
    if not cfg:
        cfg = {
            "price": 99, "days": 30,
            "backup_channel": "https://t.me/backup",
            "support_chat": "https://t.me/support"
        }
        await config_col.insert_one({"_id": "config", **cfg})
    return cfg

# === FLASK FOR 24/7 ===
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is ALIVE!"

def run_flask():
    port = int(os.getenv("PORT", 8000))
    flask_app.run(host='0.0.0.0', port=port)

# === START COMMAND ===
@app.on_message(filters.private & filters.command("start"))
async def start_cmd(c: Client, m: types.Message):
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("anime_"):
        await handle_download(c, m, args[1][6:])
        return

    if m.from_user.id == ADMIN_ID:
        await admin_panel(c, m)
        return

    cfg = await get_config()
    user = await users_col.find_one({"user_id": m.from_user.id})
    expiry = "Not Subscribed"
    if user and user.get("expiry") and user["expiry"] > datetime.utcnow():
        expiry = f"Active till *{user['expiry'].strftime('%d %b %Y')}*"

    kb = ReplyKeyboardMarkup([
        ["Subscribe Now"],
        ["Donate Now"],
        ["Join Backup", "Support"]
    ], resize_keyboard=True)

    await m.reply(
        f"*Anime Downloader\n\nSubscription:* {expiry}\n\nUse *DOWNLOAD* in channel.",
        reply_markup=kb
    )

# === ADMIN PANEL (REPLY KEYBOARD - NO INLINE) ===
async def admin_panel(c: Client, m: types.Message):
    cfg = await get_config()
    pending = await pending_sub.count_documents({})

    kb = ReplyKeyboardMarkup([
        ["Add Anime", "Add Movie"],
        ["Remove Anime", "Remove Movie"],
        ["Manage Anime", "Manage Movie"],
        ["────────────────"],
        ["Set Price & Days"],
        ["Set Sub QR", "Set Donate QR"],
        ["Set Backup", "Set Support"],
        ["View Pending"],
        ["────────────────"],
        ["Subscribe Now", "Donate Now"],
        ["Join Backup", "Support"]
    ], resize_keyboard=True)

    text = (
        f"*Admin Panel*\n\n"
        f"Price: ₹{cfg['price']} for {cfg['days']} days\n"
        f"Pending: {pending}\n\n"
        f"Click buttons to manage."
    )

    await m.reply(text, reply_markup=kb)

# === HANDLE REPLY BUTTONS (TEXT COMMANDS) ===
@app.on_message(filters.private & filters.text & filters.user(ADMIN_ID))
async def handle_admin_buttons(c: Client, m: types.Message):
    text = m.text

    if text == "Add Anime":
        await m.reply("*Add Anime\nSend **title*:")
        # Add state logic here later
    elif text == "Subscribe Now":
        await subscribe_flow_text(c, m)
    elif text == "Donate Now":
        await donate_flow_text(c, m)
    # Add more as needed

# === SUBSCRIBE (TEXT) ===
async def subscribe_flow_text(c: Client, m: types.Message):
    cfg = await get_config()
    if not cfg.get("subscription_qr_file_id"):
        return await m.reply("QR not set!")
    await c.send_photo(m.chat.id, cfg["subscription_qr_file_id"],
        caption=f"*Subscribe ₹{cfg['price']} for {cfg['days']} days*\n\nSend screenshot.")
    await users_col.update_one({"user_id": m.from_user.id}, {"$set": {"awaiting_sub": True}}, upsert=True)

# === DONATE (TEXT) ===
async def donate_flow_text(c: Client, m: types.Message):
    cfg = await get_config()
    if not cfg.get("donate_qr_file_id"):
        return await m.reply("QR not set!")
    await c.send_photo(m.chat.id, cfg["donate_qr_file_id"],
        caption="*Donate Any Amount*\n\nNo screenshot needed.")
    asyncio.create_task(thank_you(m.from_user.id))

async def thank_you(uid):
    await asyncio.sleep(3)
    await app.send_message(uid, "*Thank You!*")

# === SCREENSHOT ===
@app.on_message(filters.private & filters.photo)
async def handle_screenshot(c: Client, m: types.Message):
    user = await users_col.find_one({"user_id": m.from_user.id, "awaiting_sub": True})
    if not user: return

    sent = await m.forward(ADMIN_ID)
    kb = ReplyKeyboardMarkup([["Approve", "Reject"]], resize_keyboard=True)
    await sent.reply(f"*Pending*\nUser: {m.from_user.first_name}\nID: {m.from_user.id}", reply_markup=kb)
    await pending_sub.insert_one({"user_id": m.from_user.id, "msg_id": sent.message_id})
    await users_col.update_one({"user_id": m.from_user.id}, {"$unset": {"awaiting_sub": ""}})
    await m.reply("*Sent!*")

# === APPROVE / REJECT (TEXT) ===
@app.on_message(filters.private & filters.text & filters.user(ADMIN_ID))
async def handle_approve_reject(c: Client, m: types.Message):
    if "Pending" not in m.reply_to_message.text: return
    uid = int(m.reply_to_message.text.split("ID: ")[1].split("")[0])

    if m.text == "Approve":
        cfg = await get_config()
        expiry = datetime.utcnow() + timedelta(days=cfg["days"])
        await users_col.update_one({"user_id": uid}, {"$set": {"expiry": expiry}}, upsert=True)
        await c.send_message(uid, f"*Activated!\nTill: **{expiry.strftime('%d %b %Y')}*")
        await m.reply("*APPROVED*")
    elif m.text == "Reject":
        await c.send_message(uid, "*Rejected.*")
        await m.reply("*REJECTED*")

# === VIDEO SEND + DELETE ===
async def send_video(c: Client, chat_id, file_id, title, s, e, q):
    sent = await c.send_video(chat_id, file_id,
        caption=f"{title}** • S{s}E{e} • {q}\n\n*Forward to save\nAuto-delete in **1 min*")
    asyncio.create_task(delete_later(sent))

async def delete_later(msg):
    await asyncio.sleep(60)
    try: await msg.delete()
    except: pass

# === RUN ===
print("Bot Starting...")
threading.Thread(target=run_flask, daemon=True).start()
app.run()
