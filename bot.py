import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from yt_dlp import YoutubeDL

# --- FLASK FOR KEEP-ALIVE ---
flask_app = Flask(__name__)
@flask_app.route('/')
def hello(): return "Bot is Running"

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask, daemon=True).start()

# --- CONFIGURATION & DATA ---
API_ID = int(os.environ.get("API_ID", "12345"))
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8655737151:AAEJNKMptLd8vspEKysS7pk-GykKHl-FWXg")

# Use a dictionary to store settings so they can be updated at runtime
CONFIG = {
    "DESTINATION_ID": 0,
    "REPLACE_WORDS": {" @youtube": "", "Official": "Video"}
}

app = Client("ytdl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- UTILS ---
def get_settings_markup():
    dest = "Direct to Bot" if CONFIG["DESTINATION_ID"] == 0 else CONFIG["DESTINATION_ID"]
    buttons = [
        [InlineKeyboardButton(f"📍 Dest: {dest}", callback_data="set_dest")],
        [InlineKeyboardButton("📝 Edit Word Replacements", callback_data="set_words")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_opts(format_str, filename):
    return {
        'format': format_str,
        'outtmpl': filename,
        'noplaylist': True,
        'writethumbnail': True,
        'updatetime': False,
        'addmetadata': False,
    }

# --- HANDLERS ---

@app.on_message(filters.command("start"))
async def start(client, message):
    buttons = [
        [InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help_info")]
    ]
    await message.reply_text(
        "**YouTube Downloader Bot**\n\nSend a YouTube link to begin or tap settings to configure output.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^open_settings|back_home"))
async def settings_menu(client, query):
    await query.message.edit(
        "**Settings Menu**\nModify where files are sent and how titles are cleaned.",
        reply_markup=get_settings_markup()
    )

@app.on_callback_query(filters.regex(r"^set_dest"))
async def set_dest_handler(client, query):
    prompt = await client.ask(query.message.chat.id, "Send the new **Destination ID** (integer):\n\nTip: Use `-100...` for channels.")
    try:
        CONFIG["DESTINATION_ID"] = int(prompt.text)
        await query.message.reply(f"✅ Destination updated to `{CONFIG['DESTINATION_ID']}`")
    except ValueError:
        await query.message.reply("❌ Invalid ID. Must be a number.")
    await settings_menu(client, query)

@app.on_callback_query(filters.regex(r"^set_words"))
async def set_words_handler(client, query):
    txt = "Current Replacements:\n" + "\n".join([f"`{k}` -> `{v}`" for k, v in CONFIG["REPLACE_WORDS"].items()])
    txt += "\n\nSend new words in format: `old:new,old2:new2`"
    
    prompt = await client.ask(query.message.chat.id, txt)
    try:
        new_words = {}
        pairs = prompt.text.split(",")
        for pair in pairs:
            k, v = pair.split(":")
            new_words[k.strip()] = v.strip()
        CONFIG["REPLACE_WORDS"] = new_words
        await query.message.reply("✅ Word replacements updated.")
    except:
        await query.message.reply("❌ Formatting error. Use `word:replacement,word:replacement`.")
    await settings_menu(client, query)

# --- YOUR EXISTING DOWNLOAD LOGIC (Modified to use CONFIG dict) ---

@app.on_message(filters.regex(r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+"))
async def link_handler(client, message):
    url = message.text
    buttons = [
        [InlineKeyboardButton("360p", callback_data=f"vid|360|{url}"), InlineKeyboardButton("720p", callback_data=f"vid|720|{url}")],
        [InlineKeyboardButton("MP3 320kbps", callback_data=f"aud|320|{url}")]
    ]
    await message.reply_text("Select Format:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^(vid|aud)"))
async def download_handler(client, query):
    data = query.data.split("|")
    type, res, url = data[0], data[1], data[2]
    msg = await query.message.edit("`Processing...`")
    
    with YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'video')
        # Use Dynamic CONFIG
        for old, new in CONFIG["REPLACE_WORDS"].items():
            title = title.replace(old, new)
        filename = f"{title}.{'mp3' if type == 'aud' else 'mp4'}"
        
    f_str = f"bestvideo[height<={res}]+bestaudio/best[height<={res}]" if type == 'vid' else "bestaudio/best"
    ydl_opts = get_opts(f_str, filename)
    
    try:
        await msg.edit("`Downloading...`")
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Use Dynamic CONFIG
        target = CONFIG["DESTINATION_ID"] if CONFIG["DESTINATION_ID"] != 0 else query.message.chat.id
        
        await msg.edit("`Uploading...`")
        if type == 'vid':
            await client.send_video(target, video=filename, caption=f"**{title}**")
        else:
            await client.send_audio(target, audio=filename, caption=f"**{title}**")
        await msg.delete()
        os.remove(filename)
    except Exception as e:
        await msg.edit(f"Error: {str(e)}")

app.run()

