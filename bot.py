import os
import asyncio
import threading
import time
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyromod import listen  # Required for client.ask to work
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
BOT_TOKEN = "8655737151:AAEJNKMptLd8vspEKysS7pk-GykKHl-FWXg"

CONFIG = {
    "DESTINATION_ID": 0,
    "REPLACE_WORDS": {" @youtube": "", "Official": "Video"}
}

app = Client("ytdl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- UTILS ---
def get_progress_bar(current, total):
    percentage = current * 100 / total
    completed = int(percentage / 10)
    return f"[{'■' * completed}{'□' * (10 - completed)}] {percentage:.1f}%"

async def progress_func(current, total, msg, start_time, action):
    now = time.time()
    diff = now - start_time
    if diff < 2:  # Only update every 2 seconds to avoid Telegram flood limits
        return
    
    speed = current / diff
    bar = get_progress_bar(current, total)
    text = f"**{action}**\n\n{bar}\nSpeed: {humanbytes(speed)}/s"
    try:
        await msg.edit(text)
    except:
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

@app.on_message(filters.regex(r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+"))
async def link_handler(client, message):
    url = message.text
    buttons = [
        [InlineKeyboardButton("Video (720p)", callback_data=f"vid|720|{url}")],
        [InlineKeyboardButton("Audio (MP3)", callback_data=f"aud|320|{url}")]
    ]
    await message.reply_text("Select Format:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^(vid|aud)"))
async def download_handler(client, query):
    data = query.data.split("|")
    media_type, res, url = data[0], data[1], data[2]
    msg = await query.message.edit("`Fetching info...`")
    
    with YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'video')
        for old, new in CONFIG["REPLACE_WORDS"].items():
            title = title.replace(old, new)
        ext = 'mp3' if media_type == 'aud' else 'mp4'
        filename = f"{title}.{ext}"

    try:
        await msg.edit("`Downloading to server...`")
        ydl_opts = {
            'format': f"bestvideo[height<={res}]+bestaudio/best" if media_type == 'vid' else "bestaudio/best",
            'outtmpl': filename,
            'noplaylist': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        await msg.edit("`Preparing upload...`")
        start_time = time.time()
        target = CONFIG["DESTINATION_ID"] if CONFIG["DESTINATION_ID"] != 0 else query.message.chat.id
        
        if media_type == 'vid':
            await client.send_video(target, video=filename, caption=f"**{title}**", 
                                  progress=progress_func, progress_args=(msg, start_time, "Uploading Video"))
        else:
            await client.send_audio(target, audio=filename, caption=f"**{title}**",
                                  progress=progress_func, progress_args=(msg, start_time, "Uploading Audio"))
        
        await msg.delete()
    except Exception as e:
        await msg.edit(f"❌ Error: {str(e)}")
    finally:
        # Crucial: Delete file from server after upload or if error occurs
        if os.path.exists(filename):
            os.remove(filename)

# --- BOOTSTRAP ---
async def main():
    await app.start()
    print("Bot is alive!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
