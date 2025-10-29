import asyncio
import datetime
import os
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultArticle, InputTextMessageContent, InputMediaPhoto
)
from pymongo import MongoClient

# === SECRETS FROM ENVIRONMENT ===
# === SAFE ENVIRONMENT LOADER ===
def get_env(key, cast=None, default=None):
    value = os.getenv(key)
    if value is None:
        print(f"ERROR: {key} not set in environment!")
        return default
    if cast == int:
        try:
            return int(value)
        except:
            print(f"ERROR: {key} must be integer!")
            return default
    return value

API_ID = get_env("API_ID", cast=int)
API_HASH = get_env("API_HASH")
BOT_TOKEN = get_env("BOT_TOKEN")
MONGO_URI = get_env("MONGO_URI")
ADMIN_ID = get_env("ADMIN_ID", cast=int)

if not all([API_ID, API_HASH, BOT_TOKEN, MONGO_URI, ADMIN_ID]):
    print("FATAL: Missing secrets! Check Render.")
    exit(1)
# =================================

app = Client("anime_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
db_client = MongoClient(MONGO_URI)
db = db_client.get_default_database()  # Auto from URI
rjzone = db["rjzone"]  # Tera 1 collection

state = {}
BOT_USERNAME = None

async def delete_after(chat_id, message_id, seconds=60):
    await asyncio.sleep(seconds)
    try:
        await app.delete_messages(chat_id, message_id)
    except:
        pass

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await app.get_me()
        BOT_USERNAME = me.username

    user_id = message.from_user.id

    if user_id == ADMIN_ID:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Admin Panel", callback_data="admin_panel")]])
        await message.reply("<b>Anime Vault Pro [ADMIN]</b>\n\nClick below:", reply_markup=keyboard)
        return

    # Deep link
    if len(message.command) > 1:
        param = message.command[1]
        if param.startswith("anime_"):
            await handle_download(message, param.split("_")[1])
            return
        if param == "donate":
            await show_donate(message)
            return

    # User front with expiry
    user_doc = rjzone.find_one({"type": "user", "user_id": user_id})
    now = datetime.datetime.now()
    expiry = "Not subscribed"
    if user_doc and user_doc.get("expiry") and user_doc["expiry"] > now:
        expiry = user_doc["expiry"].strftime("%Y-%m-%d")

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Menu", switch_inline_query_current_chat="")]])

    await message.reply(
        f"<b>Anime Vault Pro</b>\n\nSubscription Expiry: <code>{expiry}</code>\n\nClick <b>Menu</b> for options.",
        reply_markup=keyboard
    )

@app.on_inline_query()
async def inline_menu(client, query):
    if query.from_user.id == ADMIN_ID:
        return

    backup_doc = rjzone.find_one({"type": "setting", "key": "backup_channel"}) or {"value": "https://t.me/yourbackup"}
    support_doc = rjzone.find_one({"type": "setting", "key": "support_chat"}) or {"value": "https://t.me/yoursupport"}
    donate_doc = rjzone.find_one({"type": "setting", "key": "donate"}) or {"value": {"amount": 50}}

    results = [
        InlineQueryResultArticle(
            title="Subscribe Now",
            input_message_content=InputTextMessageContent("Subscribe to access anime!"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Pay Now", callback_data="show_subscription")]])
        ),
        InlineQueryResultArticle(
            title=f"Donate ₹{donate_doc['value']['amount']}",
            input_message_content=InputTextMessageContent("Support the bot!"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Donate", callback_data="show_donate")]])
        ),
        InlineQueryResultArticle(
            title="Join Backup Channel",
            input_message_content=InputTextMessageContent("Join for updates!"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join", url=backup_doc["value"])]])
        ),
        InlineQueryResultArticle(
            title="Support Inbox",
            input_message_content=InputTextMessageContent("Get help!"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Contact", url=support_doc["value"])]])
        )
    ]
    await query.answer(results, cache_time=1)

@app.on_callback_query(filters.regex("^show_subscription$"))
async def show_subscription(client, query):
    sub_doc = rjzone.find_one({"type": "setting", "key": "subscription"})
    if not sub_doc:
        await query.answer("Not configured.", show_alert=True)
        return
    v = sub_doc["value"]
    caption = f"<b>Subscribe Now!</b>\n\nAmount: ₹{v['amount']}\nValidity: {v['days']} days\n\nPay & send screenshot."
    await app.send_photo(query.from_user.id, v["qr_file_id"], caption=caption)
    await query.answer()

@app.on_callback_query(filters.regex("^show_donate$"))
async def show_donate(client, query):
    donate_doc = rjzone.find_one({"type": "setting", "key": "donate"})
    if not donate_doc:
        await query.answer("Not configured.", show_alert=True)
        return
    v = donate_doc["value"]
    caption = f"<b>Donate ₹{v['amount']}</b>\n\nThank you! Send screenshot after payment."
    await app.send_photo(query.from_user.id, v["qr_file_id"], caption=caption)
    await query.answer()

@app.on_callback_query(filters.regex("^admin_panel$"))
async def admin_panel(client, query):
    if query.from_user.id != ADMIN_ID:
        await query.answer("Access denied.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Anime", callback_data="add_anime"), InlineKeyboardButton("Add Movie", callback_data="add_movie")],
        [InlineKeyboardButton("Add Season", callback_data="add_season"), InlineKeyboardButton("Add Episode", callback_data="add_episode")],
        [InlineKeyboardButton("Remove Anime", callback_data="remove_anime"), InlineKeyboardButton("Remove Movie", callback_data="remove_movie")],
        [InlineKeyboardButton("Set Subscription", callback_data="set_subscription"), InlineKeyboardButton("Set Donate QR", callback_data="set_donate")],
        [InlineKeyboardButton("Set Backup", callback_data="set_backup"), InlineKeyboardButton("Set Support", callback_data="set_support")],
        [InlineKeyboardButton("Pending Requests", callback_data="pending_requests")]
    ])
    await query.edit_message_text("<b>ADMIN PANEL</b>\nChoose an action:", reply_markup=keyboard)

@app.on_message(filters.private & filters.user(ADMIN_ID))
async def admin_messages(client, message):
    current_state = state.get(ADMIN_ID)
    if not current_state:
        return

    # Add Anime/Movie
    if current_state.endswith("_name"):
        name = message.text
        media_type = current_state.split("_")[1]
        state[ADMIN_ID] = f"add_{media_type}_thumb|{name}"
        await message.reply("Send thumbnail photo:")

    elif current_state.endswith("_thumb"):
        if not message.photo:
            await message.reply("Send a photo.")
            return
        thumb = message.photo.file_id
        media_type, name = current_state.split("_thumb|")
        media_type = media_type.split("_")[1]
        doc = {
            "type": media_type,
            "name": name,
            "thumbnail": thumb,
            "seasons": [{"season_num": 1 if media_type == "anime" else 0, "episodes": []}]
        }
        inserted_id = rjzone.insert_one(doc).inserted_id
        await message.reply("Added! Generating shareable post...")
        await generate_shareable_post(inserted_id)
        del state[ADMIN_ID]

    # Set Subscription
    elif current_state == "sub_amount":
        try:
            amount = int(message.text)
            state[ADMIN_ID] = f"sub_days|{amount}"
            await message.reply("Send days for validity:")
        except:
            await message.reply("Send a number.")

    elif current_state.startswith("sub_days|"):
        try:
            days = int(message.text)
            amount = int(current_state.split("|")[1])
            state[ADMIN_ID] = f"sub_qr|{amount}|{days}"
            await message.reply("Send QR photo:")
        except:
            await message.reply("Send a number.")

    elif current_state.startswith("sub_qr|"):
        if not message.photo:
            await message.reply("Send a photo.")
            return
        qr_id = message.photo.file_id
        parts = current_state.split("|")
        amount, days = int(parts[1]), int(parts[2])
        rjzone.update_one(
            {"type": "setting", "key": "subscription"},
            {"$set": {"value": {"amount": amount, "days": days, "qr_file_id": qr_id}}},
            upsert=True
        )
        await message.reply(f"Subscription set: ₹{amount} for {days} days.")
        del state[ADMIN_ID]

    # Set Donate
    elif current_state == "donate_amount":
        try:
            amount = int(message.text)
            state[ADMIN_ID] = f"donate_qr|{amount}"
            await message.reply("Send Donate QR photo:")
        except:
            await message.reply("Send a number.")

    elif current_state.startswith("donate_qr|"):
        if not message.photo:
            await message.reply("Send a photo.")
            return
        qr_id = message.photo.file_id
        amount = int(current_state.split("|")[1])
        rjzone.update_one(
            {"type": "setting", "key": "donate"},
            {"$set": {"value": {"amount": amount, "qr_file_id": qr_id}}},
            upsert=True
        )
        await message.reply(f"Donate QR set: ₹{amount}")
        del state[ADMIN_ID]

    # Set Backup/Support
    elif current_state == "set_backup":
        link = message.text
        rjzone.update_one({"type": "setting", "key": "backup_channel"}, {"$set": {"value": link}}, upsert=True)
        await message.reply("Backup channel set.")
        del state[ADMIN_ID]
    elif current_state == "set_support":
        link = message.text
        rjzone.update_one({"type": "setting", "key": "support_chat"}, {"$set": {"value": link}}, upsert=True)
        await message.reply("Support chat set.")
        del state[ADMIN_ID]

    # Screenshot from user (forward to admin)
@app.on_message(filters.private & filters.photo & ~filters.user(ADMIN_ID))
async def handle_screenshot(client, message):
    user_id = message.from_user.id
    user_doc = rjzone.find_one({"type": "user", "user_id": user_id})
    today = datetime.date.today()
    last_date = user_doc.get("last_screenshot_date") if user_doc else None

    if last_date and last_date == today:
        await message.reply("Only 1 screenshot per day allowed.")
        return

    pending_doc = rjzone.find_one({"type": "pending", "user_id": user_id})
    if pending_doc:
        await message.reply("Pending request already exists.")
        return

    # Update last date
    rjzone.update_one(
        {"type": "user", "user_id": user_id},
        {"$set": {"last_screenshot_date": today}},
        upsert=True
    )

    # Forward to admin
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Approve", callback_data=f"approve_{user_id}"), InlineKeyboardButton("Reject", callback_data=f"reject_{user_id}")]
    ])
    sent = await app.copy_message(ADMIN_ID, user_id, message.id, reply_markup=buttons, caption=f"Payment from user {user_id}")

    # Store pending
    rjzone.insert_one({
        "type": "pending",
        "user_id": user_id,
        "admin_msg_id": sent.id,
        "date": datetime.datetime.now()
    })

    await message.reply("Admin will verify shortly.")

@app.on_callback_query(filters.regex("^approve_|^reject_"))
async def handle_approve_reject(client, query):
    if query.from_user.id != ADMIN_ID:
        return

    parts = query.data.split("_")
    action, user_id = parts[0], int(parts[1])
    pending_doc = rjzone.find_one({"type": "pending", "user_id": user_id})

    if action == "approve":
        sub_doc = rjzone.find_one({"type": "setting", "key": "subscription"})
        if sub_doc:
            days = sub_doc["value"]["days"]
            expiry = datetime.datetime.now() + datetime.timedelta(days=days)
            rjzone.update_one(
                {"type": "user", "user_id": user_id},
                {"$set": {"expiry": expiry}},
                upsert=True
            )
            await app.send_message(user_id, f"Subscription active till {expiry.strftime('%Y-%m-%d')}.")
        # Delete after 72 hours
        asyncio.create_task(delete_after(ADMIN_ID, pending_doc["admin_msg_id"], 72*3600))
    else:
        await app.send_message(user_id, "Payment rejected.")
        await app.delete_messages(ADMIN_ID, pending_doc["admin_msg_id"])

    rjzone.delete_one({"type": "pending", "user_id": user_id})
    await query.answer(f"{action.capitalize()}d!")

# Add more callbacks and functions as per full logic (simplified for brevity)
# ... (full implementation for add/remove, download flow, etc. - use previous code snippets)

if __name__ == "__main__":

    app.run()
