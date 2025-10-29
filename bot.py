import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from threading import Thread
import requests
from datetime import datetime, timedelta

# === ENV LOADER ===
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

API_ID = get_env("API_ID", int)
API_HASH = get_env("API_HASH")
BOT_TOKEN = get_env("BOT_TOKEN")
MONGO_URI = get_env("MONGO_URI")
ADMIN_ID = get_env("ADMIN_ID", int)

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

    if args and args[0].startswith("anime_"):
        anime_id = args[0].split("_", 1)[1]
        anime = anime_col.find_one({"_id": anime_id})
        if anime:
            await show_anime(message, anime)
        else:
            await message.reply("Anime not found!")
        return

    if user_id == ADMIN_ID:
        await message.reply("*Anime Vault Pro [ADMIN]*", reply_markup=admin_kb())
    else:
        sub = users_col.find_one({"user_id": user_id})
        expiry = sub["expiry"].strftime("%d %b %Y") if sub and sub.get("expiry") else "Not subscribed"
        await message.reply(f"*Anime Vault Pro*\n\nExpiry: {expiry}\n\nChoose:", reply_markup=user_kb())

# === SHOW ANIME ===
async def show_anime(message, anime):
    kb = [[InlineKeyboardButton(f"Season {s['season_num']}", callback_data=f"season_{anime['id']}{s['season_num']}")] for s in anime["seasons"]]
    await message.reply_photo(
        anime["thumbnail"],
        caption=f"{anime['name']}\n\nChoose season:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="markdown"
    )

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
    animes = list(anime_col.find().limit(10))
    kb = [[InlineKeyboardButton(a["name"], callback_data=f"view_{a['_id']}")] for a in animes]
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
    try:
        _, anime_id, season_num = q.data.split("")
    except:
        return
    anime = anime_col.find_one({"_id": anime_id})
    if not anime: return
    season_data = next((s for s in anime["seasons"] if str(s["season_num"]) == season_num), None)
    if not season_data: return
    kb = [[InlineKeyboardButton(f"Ep {e['ep_num']}", callback_data=f"ep_{anime_id}{season_num}{e['ep_num']}")] for e in season_data["episodes"]]
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query(filters.regex("^ep_"))
async def episode(c, q):
    try:
        _, anime_id, season_num, ep_num = q.data.split("")
    except ValueError:
        await q.answer("Invalid episode!", show
