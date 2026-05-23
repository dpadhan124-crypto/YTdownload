import os
import asyncio
import threading
import time
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyromod import listen  # Required for client.ask
from yt_dlp import YoutubeDL

# --- FLASK FOR KEEP-ALIVE ---
flask_app = Flask(__name__)
@flask_app.route('/')
def hello(): return "Bot is Running"

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask, daemon=True).start()

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "12345"))
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8655737151:AAEJNKMptLd8vspEKysS7pk-GykKHl-FWXg")

CONFIG = {
    "DESTINATION_ID": 0,
    "REPLACE_WORDS": {" @youtube": "", "Official": "Video"}
}

app = Client("ytdl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- HELPER FUNCTIONS ---

def get_progress_bar(current, total, status):
    percentage = current * 100 / total
    finished_blocks = int(percentage / 10)
    remaining_blocks = 10 - finished_blocks
    bar = "✅" * finished_blocks + "⬜" * remaining_blocks
    return f"{status}: {percentage:.2f}%\n{bar}\n"

async def progress_callback(current, total, msg, start_time, status):
    try:
        now = time.time()
        diff = now - start_time
        if diff < 3: # Update every 3 seconds to avoid flood limits
            return
        
        speed = current / diff
        elapsed_time = round(diff) * 1000
        progress_str = get_progress_bar(current, total, status)
        
        await msg.edit(f"{progress_str}\nSpeed: {humanbytes(speed)}/s")
    except Exception:
        pass

def humanbytes(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.2f} {unit}"
        size /= 1024

# --- HANDLERS ---

@app.on_message(filters.command("start"))
async def start(client, message):
    buttons = [[InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")]]
    await message.reply_text("**YouTube Downloader**\nSend a link to start.", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^open_settings"))
async def settings_menu(client, query):
    dest = "Direct" if CONFIG["DESTINATION_ID"] == 0 else CONFIG["DESTINATION_ID"]
    buttons = [
        [InlineKeyboardButton(f"📍 Dest: {dest}", callback_data="set_dest")],
        [InlineKeyboardButton("⬅️ Back", callback_data="open_settings")]
    ]
    await query.message.edit("**Settings**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_message(filters.regex(r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+"))
async def link_handler(client, message):
    url = message.text
    buttons = [
        [InlineKeyboardButton("720p Video", callback_data=f"vid|720|{url}")],
        [InlineKeyboardButton("MP3 Audio", callback_data=f"aud|320|{url}")]
    ]
    await message.reply_text("Choose Format:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^(vid|aud)"))
async def download_handler(client, query):
    data = query.data.split("|")
    media_type, res, url = data[0], data[1], data[2]
    msg = await query.message.edit("`Analyzing URL...`")
    
    start_time = time.time()

    def ytdl_hook(d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%')
            s = d.get('_speed_str', 'N/A')
            # Using synchronous edit is tricky; usually we just let it download
            # For real-time progress in YTDL, custom loggers are needed.

    with YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'video')
        for old, new in CONFIG["REPLACE_WORDS"].items():
            title = title.replace(old, new)
        ext = 'mp3' if media_type == 'aud' else 'mp4'
        filename = f"{title}.{ext}"

    try:
        await msg.edit("`Downloading to Server...`")
        ydl_opts = {
            'format': f"bestvideo[height<={res}]+bestaudio/best" if media_type == 'vid' else "bestaudio/best",
            'outtmpl': filename,
            'noplaylist': True,
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        await msg.edit("`Uploading to Telegram...`")
        target = CONFIG["DESTINATION_ID"] if CONFIG["DESTINATION_ID"] != 0 else query.message.chat.id
        
        if media_type == 'vid':
            await client.send_video(
                target, video=filename, caption=f"**{title}**",
                progress=progress_callback, progress_args=(msg, start_time, "Uploading Video")
            )
        else:
            await client.send_audio(
                target, audio=filename, caption=f"**{title}**",
                progress=progress_callback, progress_args=(msg, start_time, "Uploading Audio")
            )
        
        await msg.delete()
    except Exception as e:
        await msg.edit(f"❌ Error: {str(e)}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)

# --- PROPER STARTUP FOR PYTHON 3.14 ---
async def main():
    await app.start()
    print("Bot Started!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
