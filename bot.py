import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from threading import Thread
import requests
from datetime import datetime, timedelta

# === SAFE ENV LOADER ===
def get_env(key, cast=None, default=None):
    value = os.getenv(key)
    if value is None:
        print(f"ERROR: {key} not set!")
        return default
    if cast == int:
        try:
            return int(value)
        except:
            return default
    return value

API_ID = get_env("API_ID", cast=int)
API_HASH = get_env("API_HASH")
BOT_TOKEN = get_env("BOT_TOKEN")
MONGO_URI = get_env("MONGO_URI")
ADMIN_ID = get_env("ADMIN_ID", cast=int)

if not all([API_ID, API_HASH, BOT_TOKEN, MONGO_URI, ADMIN_ID]):
    exit(1)

# === MONGO ===
client = MongoClient(MONGO_URI)
db = client["rjzone"]
anime_col = db["anime"]
users_col = db["users"]
config_col = db["config"]

# === STATE & APP ===
state = {}
app = Client("anime_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# === KEYBOARDS ===
def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Anime", callback_data="add_anime")],
        [InlineKeyboardButton("Set Sub", callback_data="set_sub")],
        [InlineKeyboardButton("Stats", callback_data="stats")]
    ])

def user_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Browse", callback_data="browse")],
        [InlineKeyboardButton("Subscribe", callback_data="subscribe")]
    ])

# === START ===
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []

    # Deep link
    if args and args[0].startswith("anime_"):
        anime_id = args[0].split("_", 1)[1]
        anime = anime_col.find_one({"_id": anime_id})
        if anime:
            await show_anime(message, anime)
        else:
            await message.reply("Anime not found!")
        return

    # Admin
    if user_id == ADMIN_ID:
        await message.reply("*Anime Vault Pro [ADMIN]*", reply_markup=admin_kb())
    else:
        sub = users_col.find_one({"user_id": user_id})
        expiry = sub["expiry"].strftime("%d %b %Y") if sub and sub.get("expiry") else "Not subscribed"
        await message.reply(f"*Anime Vault Pro*\n\nExpiry: {expiry}\n\nChoose:", reply_markup=user_kb())

# === CALLBACKS ===
@app.on_callback_query(filters.regex("^add_anime$"))
async def add_anime_cb(c, q):
    if q.from_user.id != ADMIN_ID: return
    state[ADMIN_ID] = "add_name"
    await q.edit_message_text("Send anime name:")

@app.on_callback_query(filters.regex("^set_sub$"))
async def set_sub_cb(c, q):
    if q.from_user.id != ADMIN_ID: return
    state[ADMIN_ID] = "set_amount"
    await q.edit_message_text("Send amount (₹):")

@app.on_callback_query(filters.regex("^stats$"))
async def stats(c, q):
    if q.from_user.id != ADMIN_ID: return
    total = anime_col.count_documents({})
    users = users_col.count_documents({})
    subs = users_col.count_documents({"expiry": {"$gt": datetime.now()}})
    await q.edit_message_text(f"*Stats*\n\nAnime: {total}\nUsers: {users}\nActive Subs: {subs}", reply_markup=admin_kb())

@app.on_callback_query(filters.regex("^browse$"))
async def browse(c, q):
    animes = anime_col.find().limit(10)
    kb = []
    for a in animes:
        kb.append([InlineKeyboardButton(a["name"], callback_data=f"view_{a['_id']}")])
    await q.edit_message_text("Choose anime:", reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query(filters.regex("^view_"))
async def view_anime(c, q):
    anime_id = q.data.split("_", 1)[1]
    anime = anime_col.find_one({"_id": anime_id})
    if not anime: return
    kb = [[InlineKeyboardButton(f"Season {s['season_num']}", callback_data=f"season_{anime_id}_{s['season_num']}")] for s in anime["seasons"]]
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query(filters.regex("^season_"))
async def season(c, q):
    , anime_id, season_num = q.data.split("")
    anime = anime_col.find_one({"_id": anime_id})
    season = next((s for s in anime["seasons"] if s["season_num"] == int(season_num)), None)
    if not season: return
    kb = [[InlineKeyboardButton(f"Ep {e['ep_num']}", callback_data=f"ep_{anime_id}{season_num}{e['ep_num']}")] for e in season["episodes"]]
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query(filters.regex("^ep_"))
async def episode(c, q):
    , anime_id, season_num, ep_num = q.data.split("")
    anime = anime_col.find_one({"_id": anime_id})
    season = next((s for s in anime["seasons"] if s["season_num"] == int(season_num)), None)
    ep = next((e for e in season["episodes"] if e["ep_num"] == int(ep_num)), None)
    if not ep: return
    await q.message.reply_video(ep["file_id"], caption=f"{anime['name']} - S{season_num}E{ep_num}")

# === ADMIN STATE ===
@app.on_message(filters.private & filters.user(ADMIN_ID))
async def admin_state(c, m):
    uid = m.from_user.id
    cur = state.get(uid)
    if not cur: return

    if cur == "add_name":
        name = m.text.strip()
        if not name: return await m.reply("Invalid name!")
        state[uid] = f"add_thumb|{name}"
        await m.reply("Send thumbnail photo:")

    elif cur.startswith("add_thumb|"):
        if not m.photo: return await m.reply("Send a photo!")
        thumb = m.photo.file_id
        name = cur.split("|", 1)[1]
        doc = {
            "name": name,
            "thumbnail": thumb,
            "seasons": [{"season_num": 1, "episodes": []}]
        }
        res = anime_col.insert_one(doc)
        await m.reply(f"✅ {name} added!\nShare: https://t.me/AnimeVaultProBot?start=anime_{res.inserted_id}", parse_mode="markdown")
        del state[uid]

    elif cur == "set_amount":
        try:
            amt = int(m.text)
            state[uid] = f"set_days|{amt}"
            await m.reply("Send validity (days):")
        except:
            await m.reply("Invalid amount!")

    elif cur.startswith("set_days|"):
        try:
            days = int(m.text)
            amt = int(cur.split("|", 1)[1])
            config_col.update_one({"key": "sub"}, {"$set": {"amount": amt, "days": days}}, upsert=True)
            await m.reply(f"Sub set: ₹{amt} for {days} days")
            del state[uid]
        except:
            await m.reply("Invalid days!")

# === SUBSCRIBE ===
@app.on_callback_query(filters.regex("^subscribe$"))
async def subscribe(c, q):
    config = config_col.find_one({"key": "sub"})
    if not config:
        return await q.answer("Subscription not set!", show_alert=True)
    await q.edit_message_text(
        f"*Subscribe*\n\nAmount: ₹{config['amount']}\nValidity: {config['days']} days\n\n"
        "Send payment screenshot to admin.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Pay Now", callback_data="pay")]])
    )

# === KEEP ALIVE (24/7) ===
def keep_alive():
    url = "https://rahuljaikar.onrender.com"
    while True:
        try:
            requests.get(url, timeout=10)
        except:
            pass
        asyncio.run(asyncio.sleep(300))

Thread(target=keep_alive, daemon=True).start()

print("Bot started!")
app.run()
