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

# === ADMIN STATE ===
admin_states = {}

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

# === ADMIN PANEL ===
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

# === HANDLE ADMIN BUTTONS ===
@app.on_message(filters.private & filters.text & filters.user(ADMIN_ID))
async def handle_admin_buttons(c: Client, m: types.Message):
    text = m.text.strip()

    if text == "Add Anime":
        admin_states[m.from_user.id] = {"step": "title", "data": {"type": "anime", "seasons": []}}
        await m.reply("*Add Anime\nSend **title*:")

    elif text == "Add Movie":
        admin_states[m.from_user.id] = {"step": "title", "data": {"type": "movie"}}
        await m.reply("*Add Movie\nSend **title*:")

    elif text == "Subscribe Now":
        await subscribe_flow_text(c, m)

    elif text == "Donate Now":
        await donate_flow_text(c, m)

    elif text == "View Pending":
        pending = await pending_sub.find({}).to_list(10)
        if not pending:
            await m.reply("No pending payments.")
        else:
            msg = "*Pending Payments:*\n"
            for p in pending:
                try:
                    user = await c.get_users(p["user_id"])
                    msg += f"\n• {user.first_name} ({p['user_id']})"
                except:
                    msg += f"\n• User {p['user_id']}"
            await m.reply(msg)

# === HANDLE TEXT INPUT (ADD ANIME FLOW) ===
@app.on_message(filters.private & filters.text & ~filters.command)
async def handle_text_input(c: Client, m: types.Message):
    user_id = m.from_user.id

    # Admin flow
    if user_id == ADMIN_ID and user_id in admin_states:
        state = admin_states[user_id]
        step = state["step"]

        if step == "title":
            title = m.text.strip()
            state["data"]["title"] = title
            state["step"] = "thumb"
            await m.reply("*Thumbnail bhejo* (photo):")

        elif step == "thumb" and m.photo:
            file_id = m.photo.file_id
            state["data"]["thumb_file_id"] = file_id
            state["step"] = "season" if state["data"]["type"] == "anime" else "quality"
            if state["data"]["type"] == "anime":
                await m.reply("*Season number daalo* (1, 2, etc):")
            else:
                await m.reply("*Quality daalo* (480p, 720p, 1080p):")

        elif step == "season":
            try:
                season = int(m.text)
                state["data"]["current_season"] = season
                state["step"] = "episode"
                await m.reply(f"*S{season}E?* Episode number daalo:")
            except:
                await m.reply("Number daalo!")

        elif step == "episode":
            try:
                ep = int(m.text)
                state["data"]["current_episode"] = ep
                state["step"] = "quality"
                await m.reply(f"*S{state['data']['current_season']}E{ep}*\nQuality daalo (480p, 720p, 1080p):")
            except:
                await m.reply("Number daalo!")

        elif step == "quality":
            quality = m.text.strip()
            state["data"]["current_quality"] = quality
            state["step"] = "video"
            await m.reply(f"{quality} video bhejo** (forward from channel):")

        elif step == "video" and m.video:
            file_id = m.video.file_id
            data = state["data"]
            anime_id = f"{data['title'].lower().replace(' ', '_')}"

            if data["type"] == "anime":
                await anime_col.update_one(
                    {"_id": anime_id},
                    {"$set": {"title": data["title"], "thumb_file_id": data["thumb_file_id"]},
                     "$push": {"seasons": {
                         "season_num": data["current_season"],
                         "episodes": [{
                             "episode_num": data["current_episode"],
                             "files": [{"quality": data["current_quality"], "file_id": file_id}]
                         }]
                     }}},
                    upsert=True
                )
            else:
                await anime_col.insert_one({
                    "_id": anime_id,
                    "title": data["title"],
                    "thumb_file_id": data["thumb_file_id"],
                    "type": "movie",
                    "files": [{"quality": data["current_quality"], "file_id": file_id}]
                })

            await m.reply(f"{data['title']} added!")
            del admin_states[user_id]

# === SUBSCRIBE ===
async def subscribe_flow_text(c: Client, m: types.Message):
    cfg = await get_config()
    if not cfg.get("subscription_qr_file_id"):
        return await m.reply("QR not set!")
    await c.send_photo(m.chat.id, cfg["subscription_qr_file_id"],
        caption=f"*Subscribe ₹{cfg['price']} for {cfg['days']} days*\n\nSend screenshot.")
    await users_col.update_one({"user_id": m.from_user.id}, {"$set": {"awaiting_sub": True}}, upsert=True)

# === DONATE ===
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

# === APPROVE / REJECT ===
@app.on_message(filters.private & filters.text & filters.user(ADMIN_ID))
async def handle_approve_reject(c: Client, m: types.Message):
    if not m.reply_to_message or "Pending" not in m.reply_to_message.text: return
    try:
        uid = int(m.reply_to_message.text.split("ID: ")[1].split("")[0])
    except: return

    if m.text == "Approve":
        cfg = await get_config()
        expiry = datetime.utcnow() + timedelta(days=cfg["days"])
        await users_col.update_one({"user_id": uid}, {"$set": {"expiry": expiry}}, upsert=True)
        await c.send_message(uid, f"*Activated!\nTill: **{expiry.strftime('%d %b %Y')}*")
        await m.reply("*APPROVED*")
    elif m.text == "Reject":
        await c.send_message(uid, "*Rejected.*")
        await m.reply("*REJECTED*")

# === DOWNLOAD ===
async def handle_download(c: Client, m: types.Message, anime_id: str):
    user = await users_col.find_one({"user_id": m.from_user.id})
    if not user or not user.get("expiry") or user["expiry"] < datetime.utcnow():
        kb = ReplyKeyboardMarkup([["Subscribe Now"]], resize_keyboard=True)
        return await m.reply("*Subscribe first.*", reply_markup=kb)

    anime = await anime_col.find_one({"_id": anime_id})
    if not anime: return await m.reply("Not found.")

    kb = ReplyKeyboardMarkup([
        [f"S{s['season_num']}" for s in anime.get("seasons", [])[:2]]
    ], resize_keyboard=True)
    await c.send_photo(m.chat.id, anime["thumb_file_id"], "*Select Season:*", reply_markup=kb)

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

