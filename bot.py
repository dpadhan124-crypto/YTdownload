import os
import asyncio
import threading
import time
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyromod import listen  # Necessary for client.ask
from yt_dlp import YoutubeDL

# --- FLASK FOR KEEP-ALIVE ---
flask_app = Flask(__name__)
@flask_app.route('/')
def hello(): return "Bot is Running"

def run_flask():
    # Use port 8080 or the one assigned by Render
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

# Create the client without running it yet
app = Client("ytdl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- PROGRESS BAR UTILS ---

def humanbytes(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.2f} {unit}"
        size /= 1024

async def progress_bar(current, total, msg, start_time, action):
    now = time.time()
    diff = now - start_time
    if diff < 3: # Update every 3 seconds to avoid Telegram rate limits
        return
    
    percentage = current * 100 / total
    speed = current / diff
    elapsed_time = round(diff)
    
    # Visual Bar
    completed = int(percentage / 10)
    bar = "🟢" * completed + "⚪" * (10 - completed)
    
    progress_text = (
        f"**{action}**\n\n"
        f"📊 {bar} {percentage:.1f}%\n"
        f"🚀 Speed: {humanbytes(speed)}/s\n"
        f"📦 Done: {humanbytes(current)} of {humanbytes(total)}"
    )
    
    try:
        await msg.edit_text(progress_text)
    except:
        pass

# --- HANDLERS ---

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("**YouTube Downloader Ready**\nSend a link to begin.")

@app.on_message(filters.regex(r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+"))
async def link_handler(client, message):
    url = message.text
    buttons = [
        [InlineKeyboardButton("🎬 Video 720p", callback_data=f"vid|720|{url}")],
        [InlineKeyboardButton("🎵 Audio MP3", callback_data=f"aud|320|{url}")]
    ]
    await message.reply_text("Choose Format:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^(vid|aud)"))
async def download_handler(client, query):
    data = query.data.split("|")
    media_type, res, url = data[0], data[1], data[2]
    msg = await query.message.edit("`Extracting link...`")
    
    # 1. Title Cleaning
    with YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'video')
        for old, new in CONFIG["REPLACE_WORDS"].items():
            title = title.replace(old, new)
        ext = 'mp3' if media_type == 'aud' else 'mp4'
        filename = f"{title}.{ext}"

    try:
        # 2. Download from YouTube
        await msg.edit("`Downloading to server...`")
        ydl_opts = {
            'format': f"bestvideo[height<={res}]+bestaudio/best" if media_type == 'vid' else "bestaudio/best",
            'outtmpl': filename,
            'noplaylist': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # 3. Upload to Telegram with Progress
        start_time = time.time()
        target = CONFIG["DESTINATION_ID"] if CONFIG["DESTINATION_ID"] != 0 else query.message.chat.id
        
        await msg.edit("`Uploading...`")
        if media_type == 'vid':
            await client.send_video(
                target, video=filename, caption=f"**{title}**",
                progress=progress_bar, progress_args=(msg, start_time, "Uploading Video")
            )
        else:
            await client.send_audio(
                target, audio=filename, caption=f"**{title}**",
                progress=progress_bar, progress_args=(msg, start_time, "Uploading Audio")
            )
        
        await msg.delete()

    except Exception as e:
        await msg.edit(f"❌ Error: {str(e)}")
    
    finally:
        # 4. CRITICAL: Always delete file after upload or failure
        if os.path.exists(filename):
            os.remove(filename)

# --- BOOTSTRAP (FIX FOR PYTHON 3.14) ---

async def main():
    # This manually starts the client in the current event loop
    await app.start()
    print("Bot is successfully running on Python 3.14!")
    # Keep the loop alive
    await asyncio.Event().wait()

if __name__ == "__main__":
    # Standard way to run async in Python 3.14
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
