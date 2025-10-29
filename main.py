# main.py
import os
import asyncio
import threading
from datetime import datetime, timedelta
from pyrogram import Client, filters, types
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from flask import Flask

# === CONFIG FROM RENDER ENVIRONMENT (NO .env) ===
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

# === ADMIN STATE ===
admin_states = {}

# === FLASK FOR 24/7 (RENDER) ===
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Anime Bot is ALIVE! 24/7"

def run_flask():
    port = int(os.getenv("PORT", 8000))
    flask_app.run(host='0.0.0.0', port=port)

# === START COMMAND (ADMIN = DIRECT PANEL) ===
@app.on_message(filters.private & filters.command("start"))
async def start_cmd(c: Client, m: types.Message):
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("anime_"):
        await handle_download(c, m, args[1][6:])
        return

    # ADMIN = DIRECT PANEL
    if m.from_user.id == ADMIN_ID:
        await admin_panel(c, m)
        return

    # NORMAL USER
    cfg = await get_config()
    user = await users_col.find_one({"user_id": m.from_user.id})
    expiry = "Not Subscribed"
    if user and user.get("expiry") and user["expiry"] > datetime.utcnow():
        expiry = f"Active till *{user['expiry'].strftime('%d %b %Y')}*"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Subscribe Now", callback_data="subscribe")],
        [InlineKeyboardButton("Donate Now", callback_data="donate")],
        [InlineKeyboardButton("Join Backup", url=cfg["backup_channel"])],
        [InlineKeyboardButton("Support", url=cfg["support_chat"])],
    ])

    await m.reply(
        f"*Anime Downloader\n\nSubscription:* {expiry}\n\nUse *DOWNLOAD* in channel.",
        reply_markup=kb
    )

# === ADMIN PANEL (3-LINE INLINE) ===
async def admin_panel(c: Client, m: types.Message):
    cfg = await get_config()
    pending = await pending_sub.count_documents({})

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Anime", callback_data="add_anime"),
         InlineKeyboardButton("Add Movie", callback_data="add_movie")],
        [InlineKeyboardButton("Remove Anime", callback_data="rem_anime"),
         InlineKeyboardButton("Remove Movie", callback_data="rem_movie")],
        [InlineKeyboardButton("Manage Anime", callback_data="manage_anime"),
         InlineKeyboardButton("Manage Movie", callback_data="manage_movie")],
        [],
        [InlineKeyboardButton("Set Price & Days", callback_data="set_price")],
        [InlineKeyboardButton("Set Sub QR", callback_data="set_sub_qr")],
        [InlineKeyboardButton("Set Donate QR", callback_data="set_donate_qr")],
        [InlineKeyboardButton("Set Backup", callback_data="set_backup")],
        [InlineKeyboardButton("Set Support", callback_data="set_support")],
        [InlineKeyboardButton("View Pending", callback_data="view_pending")],
        [],
        [InlineKeyboardButton("Subscribe Now", callback_data="subscribe")],
        [InlineKeyboardButton("Donate Now", callback_data="donate")],
        [InlineKeyboardButton("Join Backup", url=cfg["backup_channel"])],
        [InlineKeyboardButton("Support", url=cfg["support_chat"])],
    ])

    text = (
        f"*Admin Panel*\n\n"
        f"Price: ₹{cfg['price']} for {cfg['days']} days\n"
        f"Pending: {pending}\n\n"
        f"Manage anime, payments & settings."
    )

    await m.reply(text, reply_markup=kb)

# === SUBSCRIBE ===
@app.on_callback_query(filters.regex("^subscribe$"))
async def subscribe_flow(c: Client, cq: types.CallbackQuery):
    cfg = await get_config()
    if not cfg.get("subscription_qr_file_id"):
        return await cq.answer("QR not set!", show_alert=True)
    await cq.message.delete()
    await c.send_photo(cq.from_user.id, cfg["subscription_qr_file_id"],
        caption=f"*Subscribe ₹{cfg['price']} for {cfg['days']} days*\n\nSend screenshot.")
    await users_col.update_one({"user_id": cq.from_user.id}, {"$set": {"awaiting_sub": True}}, upsert=True)

# === DONATE ===
@app.on_callback_query(filters.regex("^donate$"))
async def donate_flow(c: Client, cq: types.CallbackQuery):
    cfg = await get_config()
    if not cfg.get("donate_qr_file_id"):
        return await cq.answer("QR not set!", show_alert=True)
    await cq.message.delete()
    await c.send_photo(cq.from_user.id, cfg["donate_qr_file_id"],
        caption="*Donate Any Amount*\n\nNo screenshot needed.")
    asyncio.create_task(thank_you(cq.from_user.id))

async def thank_you(uid):
    await asyncio.sleep(3)
    await app.send_message(uid, "*Thank You for Your Support!*")

# === SCREENSHOT ===
@app.on_message(filters.private & filters.photo)
async def handle_screenshot(c: Client, m: types.Message):
    user = await users_col.find_one({"user_id": m.from_user.id, "awaiting_sub": True})
    if not user: return

    sent = await m.forward(ADMIN_ID)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Approve", callback_data=f"approve_{m.from_user.id}"),
         InlineKeyboardButton("Reject", callback_data=f"reject_{m.from_user.id}")]
    ])
    await sent.reply(f"*Pending*\nUser: {m.from_user.first_name}\nID: {m.from_user.id}", reply_markup=kb)
    await pending_sub.insert_one({"user_id": m.from_user.id, "msg_id": sent.message_id, "added_at": datetime.utcnow()})
    await users_col.update_one({"user_id": m.from_user.id}, {"$unset": {"awaiting_sub": ""}})
    await m.reply("*Screenshot sent!*")

# === APPROVE / REJECT ===
@app.on_callback_query(filters.regex("^approve_"))
async def approve(c: Client, cq: types.CallbackQuery):
    uid = int(cq.data.split("_")[1])
    cfg = await get_config()
    expiry = datetime.utcnow() + timedelta(days=cfg["days"])
    await users_col.update_one({"user_id": uid}, {"$set": {"expiry": expiry}}, upsert=True)
    await c.send_message(uid, f"*Activated!\nTill: **{expiry.strftime('%d %b %Y')}*")
    await cq.message.edit_text(f"{cq.message.text}\n\n*APPROVED*")

@app.on_callback_query(filters.regex("^reject_"))
async def reject(c: Client, cq: types.CallbackQuery):
    uid = int(cq.data.split("_")[1])
    await c.send_message(uid, "*Rejected.*")
    await cq.message.edit_text(f"{cq.message.text}\n\n*REJECTED*")

# === DOWNLOAD FLOW ===
async def handle_download(c: Client, m: types.Message, anime_id: str):
    user = await users_col.find_one({"user_id": m.from_user.id})
    if not user or not user.get("expiry") or user["expiry"] < datetime.utcnow():
        kb = [[InlineKeyboardButton("Subscribe Now", callback_data="subscribe")]]
        return await m.reply("*Subscribe first.*", reply_markup=InlineKeyboardMarkup(kb))

    anime = await anime_col.find_one({"_id": anime_id})
    if not anime: return await m.reply("Not found.")

    kb = [[InlineKeyboardButton(f"Season {s['season_num']}", callback_data=f"s_{anime_id}_{s['season_num']}")] 
          for s in anime.get("seasons", [])]
    await c.send_photo(m.chat.id, anime["thumb_file_id"], "*Select Season:*", reply_markup=InlineKeyboardMarkup(kb))

# === VIDEO SEND + 1 MIN DELETE ===
async def send_video(c: Client, chat_id, file_id, title, s, e, q):
    sent = await c.send_video(
        chat_id, file_id,
        caption=f"{title}** • S{s}E{e} • {q}\n\n*Forward to save\nAuto-delete in **1 min*"
    )
    asyncio.create_task(delete_later(sent))

async def delete_later(msg):
    await asyncio.sleep(60)
    try: await msg.delete()
    except: pass

# === ADD ANIME (BASIC) ===
@app.on_callback_query(filters.regex("^add_anime$"))
async def add_anime_start(c: Client, cq: types.CallbackQuery):
    admin_states[cq.from_user.id] = {"step": "title", "data": {"type": "anime", "seasons": [{"season_num": 1, "episodes": []}]}}
    await cq.message.edit_text("*Add Anime\nSend **title*:")

# === RUN BOT + FLASK ===
print("Starting Flask + Bot...")
threading.Thread(target=run_flask, daemon=True).start()
app.run()
