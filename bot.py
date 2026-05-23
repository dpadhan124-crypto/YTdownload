import os
import asyncio
import threading
import time
from flask import Flask

# --- CRITICAL FIX FOR PYROGRAM ON MODERN PYTHON ---
# We must create and set an event loop BEFORE importing pyrogram to prevent the "RuntimeError: There is no current event loop" crash.
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

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

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "12345"))
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8655737151:AAEJNKMptLd8vspEKysS7pk-GykKHl-FWXg")

# Semaphore to control concurrent worker downloads (Multi-worker pool)
MAX_CONCURRENT_DOWNLOADS = 4
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

app = Client("ytdl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- UTILS ---
def humanbytes(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.2f} {unit}"
        size /= 1024

async def progress_bar(current, total, msg, start_time, action):
    now = time.time()
    diff = now - start_time
    if diff < 4: 
        return
    percentage = (current * 100 / total) if total else 0
    speed = current / diff if diff > 0 else 0
    
    completed = int(percentage / 10)
    bar = "🟢" * completed + "⚪" * (10 - completed)
    
    progress_text = (
        f"**{action}**\n\n"
        f"📊 {bar} {percentage:.1f}%\n"
        f"🚀 Speed: {humanbytes(speed)}/s\n"
        f"📦 Done: {humanbytes(current)} of {humanbytes(total if total else current)}"
    )
    try:
        await msg.edit_text(progress_text)
    except:
        pass

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 **High-Speed YT Downloader Ready**\nSend a video or playlist link to begin.")

@app.on_message(filters.regex(r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+"))
async def link_handler(client, message):
    url = message.text
    buttons = [
        [
            InlineKeyboardButton("🎬 1080p Video", callback_data=f"dl|1080|{url}"),
            InlineKeyboardButton("🎬 720p Video", callback_data=f"dl|720|{url}")
        ],
        [
            InlineKeyboardButton("🎬 480p Video", callback_data=f"dl|480|{url}"),
            InlineKeyboardButton("🎵 Audio 48kbps", callback_data=f"dl|48k|{url}")
        ]
    ]
    await message.reply_text("⚡ **Select Quality Preference:**\n_(Works for single videos and playlists)_", reply_markup=InlineKeyboardMarkup(buttons))

async def download_worker(client, url, quality, chat_id):
    """Worker task that downloads and uploads an individual file."""
    async with download_semaphore:
        msg = await client.send_message(chat_id, "⏳ `Processing link details...`")
        
        # Configure High-Speed multi-threaded options for yt-dlp
        ydl_opts = {
            'quiet': True,
            'noplaylist': True, 
            'nocheckcertificate': True,
            # external_downloader args force multi-connection chunks for speed boost
            'external_downloader': 'aria2c',
            'external_downloader_args': ['-x', '16', '-s', '16', '-k', '1M'],
        }

        if quality == "48k":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'outtmpl': '%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '48', # Forces 48kbps bitrate
                }],
            })
        else:
            ydl_opts.update({
                'format': f"bestvideo[height<={quality}]+bestaudio/best",
                'outtmpl': '%(title)s.%(ext)s',
                'merge_output_format': 'mp4'
            })

        try:
            # Extract info safely inside an executor pool thread
            loop = asyncio.get_running_loop()
            with YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                filename = ydl.prepare_filename(info)
                if quality == "48k":
                    filename = os.path.splitext(filename)[0] + ".mp3"
                elif not filename.endswith(".mp4"):
                    filename = os.path.splitext(filename)[0] + ".mp4"

            await msg.edit("⚡ `Downloading from YouTube at Max Speed...`")
            with YoutubeDL(ydl_opts) as ydl:
                await loop.run_in_executor(None, lambda: ydl.download([url]))

            if not os.path.exists(filename):
                # Fallback if names mismatched slightly due to merging formats
                base, _ = os.path.splitext(filename)
                if os.path.exists(f"{base}.mp4"): filename = f"{base}.mp4"
                elif os.path.exists(f"{base}.mkv"): filename = f"{base}.mkv"

            start_time = time.time()
            await msg.edit("📤 `Uploading file to Telegram...`")
            
            if quality == "48k":
                await client.send_audio(
                    chat_id, audio=filename, caption=f"🎵 **{info.get('title')}** [48kbps]",
                    progress=progress_bar, progress_args=(msg, start_time, "Uploading Audio")
                )
            else:
                await client.send_video(
                    chat_id, video=filename, caption=f"🎬 **{info.get('title')}** [{quality}p]",
                    progress=progress_bar, progress_args=(msg, start_time, "Uploading Video")
                )
            await msg.delete()

        except Exception as e:
            await msg.edit(f"❌ **Error handling video:**\n`{str(e)}`")
        
        finally:
            if 'filename' in locals() and os.path.exists(filename):
                try: os.remove(filename)
                except: pass

@app.on_callback_query(filters.regex(r"^dl\|"))
async def process_callback(client, query):
    _, quality, url = query.data.split("|")
    chat_id = query.message.chat.id
    await query.answer("Job added to multi-worker queue...")
    await query.message.delete()

    # Playlist structural check
    with YoutubeDL({'extract_flat': True, 'quiet': True}) as ydl:
        meta = ydl.extract_info(url, download=False)
        
    if 'entries' in meta: # It's a playlist!
        entries = list(meta['entries'])
        status_msg = await client.send_message(chat_id, f"📦 **Playlist detected!** Found `{len(entries)}` items.\nProcessing asynchronous multi-worker download queue...")
        
        # Dispatch workers concurrently for playlist files
        tasks = []
        for entry in entries:
            video_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
            tasks.append(download_worker(client, video_url, quality, chat_id))
        
        await asyncio.gather(*tasks)
        await status_msg.edit("✅ All playlist items have finished processing!")
    else:
        # Single video handling
        await download_worker(client, url, quality, chat_id)

if __name__ == "__main__":
    app.run()

