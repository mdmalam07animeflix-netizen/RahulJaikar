# main.py
import os
import asyncio
import threading
from datetime import datetime, timedelta
from pyrogram import Client, filters, types
from pyrogram.types import ReplyKeyboardMarkup
from motor.motor_asyncio import AsyncIOMotorClient
from flask import Flask

# === CONFIG ===
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

# === STATE ===
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

# === FLASK 24/7 ===
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Bot is ALIVE!"
def run_flask():
    port = int(os.getenv("PORT", 8000))
    flask_app.run(host='0.0.0.0', port=port)

# === START ===
@app.on_message(filters.private & filters.command("start"))
async def start_cmd(c: Client, m: types.Message):
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
        f"*Anime Downloader\n\nSubscription:* {expiry}\n\nUse *DOWNLOAD* in group.",
        reply_markup=kb
    )

# === ADMIN PANEL ===
async def admin_panel(c: Client, m: types.Message):
    cfg = await get_config()
    pending = await pending_sub.count_documents({})

    kb = ReplyKeyboardMarkup([
        ["Add Anime", "Add Movie"],
        ["Remove Anime", "Remove Movie"],
        ["────────────────"],
        ["Set Price & Days"],
        ["Set Sub QR", "Set Donate QR"],
        ["Set Backup", "Set Support"],
        ["View Pending"],
        ["────────────────"],
        ["Subscribe Now", "Donate Now"],
        ["Join Backup", "Support"]
    ], resize_keyboard=True)

    await m.reply(
        f"*Admin Panel*\n\nPrice: ₹{cfg['price']} for {cfg['days']} days\nPending: {pending}\n\nClick buttons to manage.",
        reply_markup=kb
    )

# === ADMIN BUTTONS ===
@app.on_message(filters.private & filters.text & filters.user(ADMIN_ID))
async def handle_admin_buttons(c: Client, m: types.Message):
    text = m.text.strip()

    if text == "Add Anime":
        admin_states[m.from_user.id] = {"step": "title", "data": {"type": "anime", "seasons": []}}
        await m.reply("*Add Anime\nSend **title*:")

    elif text == "Subscribe Now":
        await subscribe_flow_text(c, m)

    elif text == "Donate Now":
        await donate_flow_text(c, m)

# === TEXT INPUT (ADD ANIME) ===
@app.on_message(filters.private & filters.text)
async def handle_text_input(c: Client, m: types.Message):
    if m.text.startswith("/"): return
    if m.from_user.id != ADMIN_ID: return
    if m.from_user.id not in admin_states: return

    state = admin_states[m.from_user.id]
    step = state["step"]

    if step == "title":
        state["data"]["title"] = m.text.strip()
        state["step"] = "thumb"
        await m.reply("*Thumbnail bhejo* (photo):")

    elif step == "thumb" and m.photo:
        state["data"]["thumb_file_id"] = m.photo.file_id
        state["step"] = "season" if state["data"]["type"] == "anime" else "quality"
        await m.reply("*Season number daalo* (1, 2, etc):" if state["data"]["type"] == "anime" else "*Quality daalo*:")

    elif step == "season":
        try:
            state["data"]["current_season"] = int(m.text)
            state["step"] = "episode"
            await m.reply(f"*S{int(m.text)}E?* Episode number daalo:")
        except: await m.reply("Number daalo!")

    elif step == "episode":
        try:
            state["data"]["current_episode"] = int(m.text)
            state["step"] = "quality"
            await m.reply(f"*S{state['data']['current_season']}E{int(m.text)}*\nQuality daalo:")
        except: await m.reply("Number daalo!")

    elif step == "quality":
        state["data"]["current_quality"] = m.text.strip()
        state["step"] = "video"
        await m.reply(f"{m.text.strip()} video bhejo** (forward from group):")

    elif step == "video" and m.video:
        file_id = m.video.file_id
        data = state["data"]
        anime_id = f"{data['title'].lower().replace(' ', '_')}"

        # Save to DB
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

        # AUTO POST IN GROUP
        cfg = await get_config()
        kb = ReplyKeyboardMarkup([
            ["Join Backup", "Support"],
            ["Download", "Donate Now"]
        ], resize_keyboard=True)

        caption = (
            f"{data['title']}\n"
            f"S{data['current_season']}E{data['current_episode']} • {data['current_quality']}\n\n"
            f"*Forward to save! Auto-delete in 1 min*\n"
            f"Use *Download* button below."
        )

        sent = await c.send_photo(
            GROUP_ID,
            data["thumb_file_id"],
            caption=caption,
            reply_markup=kb
        )

        # Save message for download
        await anime_col.update_one(
            {"_id": anime_id, "seasons.season_num": data["current_season"], "seasons.episodes.episode_num": data["current_episode"]},
            {"$set": {"seasons.$[].episodes.$[].group_msg_id": sent.message_id}}
        )

        del admin_states[m.from_user.id]

# === DOWNLOAD FROM GROUP ===
@app.on_message(filters.group & filters.text & filters.regex("^Download$"))
async def handle_download_button(c: Client, m: types.Message):
    if m.reply_to_message is None: return

    # Find anime from group message
    anime = await anime_col.find_one({"seasons.episodes.group_msg_id": m.reply_to_message.message_id})
    if not anime: return

    user = await users_col.find_one({"user_id": m.from_user.id})
    if not user or not user.get("expiry") or user["expiry"] < datetime.utcnow():
        await m.reply("*Subscribe first to download!*", reply_markup=ReplyKeyboardMarkup([["Subscribe Now"]]))
        return

    # Find video
    for s in anime.get("seasons", []):
        for e in s.get("episodes", []):
            if e.get("group_msg_id") == m.reply_to_message.message_id:
                file_id = e["files"][0]["file_id"]
                title = anime["title"]
                s_num = s["season_num"]
                e_num = e["episode_num"]
                q = e["files"][0]["quality"]

                sent = await c.send_video(
                    m.from_user.id,
                    file_id,
                    caption=f"{title}** • S{s_num}E{e_num} • {q}\n\n*Forward this message to save! Auto-delete in 1 min*"
                )
                asyncio.create_task(delete_later(sent))
                return

# === SUBSCRIBE / DONATE ===
async def subscribe_flow_text(c: Client, m: types.Message):
    cfg = await get_config()
    if not cfg.get("subscription_qr_file_id"):
        return await m.reply("QR not set!")
    await c.send_photo(m.chat.id, cfg["subscription_qr_file_id"],
        caption=f"*Subscribe ₹{cfg['price']} for {cfg['days']} days*\n\nSend screenshot.")
    await users_col.update_one({"user_id": m.from_user.id}, {"$set": {"awaiting_sub": True}}, upsert=True)

async def donate_flow_text(c: Client, m: types.Message):
    cfg = await get_config()
    if not cfg.get("donate_qr_file_id"):
        return await m.reply("QR not set!")
    await c.send_photo(m.chat.id, cfg["donate_qr_file_id"],
        caption="*Donate Any Amount*\n\nNo screenshot needed.")

# === SCREENSHOT & APPROVE ===
@app.on_message(filters.private & filters.photo)
async def handle_screenshot(c: Client, m: types.Message):
    user = await users_col.find_one({"user_id": m.from_user.id, "awaiting_sub": True})
    if not user: return

    sent = await m.forward(ADMIN_ID)
    kb = ReplyKeyboardMarkup([["Approve", "Reject"]], resize_keyboard=True)
    await sent.reply(f"*Pending*\nUser: {m.from_user.first_name}\nID: {m.from_user.id}", reply_markup=kb)
    await pending_sub.insert_one({"user_id": m.from_user.id, "msg_id": sent.message_id})
    await users_col.update_one({"user_id": m.from_user.id}, {"$unset": {"awaiting_sub": ""}})
    await m.reply("*Screenshot sent!*")

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
        await c.send_message(uid, f"*Subscription Activated!\nValid till: **{expiry.strftime('%d %b %Y')}*")
        await m.reply("*APPROVED*")
    elif m.text == "Reject":
        await c.send_message(uid, "*Subscription Rejected.*")
        await m.reply("*REJECTED*")

# === DELETE AFTER 1 MIN ===
async def delete_later(msg):
    await asyncio.sleep(60)
    try: await msg.delete()
    except: pass

# === RUN ===
threading.Thread(target=run_flask, daemon=True).start()
app.run()
