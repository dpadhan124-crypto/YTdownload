import os
import asyncio
import threading
import time
import re
import glob
from flask import Flask

# --- CRITICAL FIX FOR PYROGRAM ON MODERN PYTHON ---
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
MAX_CONCURRENT_DOWNLOADS = 3
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

app = Client("ytdl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- UTILS & FORMATTING ---
def humanbytes(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.2f} {unit}"
        size /= 1024

def time_formatter(seconds):
    if not seconds: return "0s"
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours: return f"{hours}h {minutes}m {seconds}s"
    if minutes: return f"{minutes}m {seconds}s"
    return f"{seconds}s"

async def progress_bar(current, total, msg, start_time, action, title="", extra_info=""):
    now = time.time()
    diff = now - start_time
    if diff < 3: 
        return
    percentage = (current * 100 / total) if total else 0
    speed = current / diff if diff > 0 else 0
    eta = ((total - current) / speed) if speed > 0 and total else 0
    
    completed = int(percentage / 10)
    bar = "🟢" * completed + "⚪" * (10 - completed)
    
    context = f"📁 **File:** `{title}`\n" if title else ""
    idx_info = f"📦 **Status:** {extra_info}\n" if extra_info else ""
    
    progress_text = (
        f"⏳ **{action}**\n\n"
        f"{context}{idx_info}"
        f"📊 {bar} {percentage:.1f}%\n"
        f"🚀 Speed: `{humanbytes(speed)}/s`\n"
        f"📦 Processed: `{humanbytes(current)}` of `{humanbytes(total if total else current)}`\n"
        f"⏱️ ETA: `{time_formatter(eta)}`"
    )
    try:
        await msg.edit_text(progress_text)
    except:
        pass

# --- CUSTOM YT-DLP HOOKS FOR REAL-TIME UPDATE ---
class YtdlProgressHook:
    def __init__(self, client, chat_id, msg, title, extra_info):
        self.client = client
        self.chat_id = chat_id
        self.msg = msg
        self.title = title
        self.extra_info = extra_info
        self.start_time = time.time()
        self.last_update = 0

    def __call__(self, d):
        if d['status'] == 'downloading':
            now = time.time()
            if now - self.last_update < 4:
                return
            self.last_update = now
            
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            current = d.get('downloaded_bytes', 0)
            percentage = (current * 100 / total) if total else 0
            speed = d.get('speed', 0) or 0
            eta = d.get('eta', 0) or 0
            
            completed = int(percentage / 10)
            bar = "📥" * completed + "⚪" * (10 - completed)
            
            context = f"📁 **Downloading:** `{self.title}`\n"
            idx_info = f"📦 **Progress:** {self.extra_info}\n" if self.extra_info else ""
            
            text = (
                f"⚡ **Downloading Chunk via yt-dlp**\n\n"
                f"{context}{idx_info}"
                f"📊 {bar} {percentage:.1f}%\n"
                f"🚀 Speed: `{humanbytes(speed)}/s`\n"
                f"📦 Size: `{humanbytes(current)}` / `{humanbytes(total)}`\n"
                f"⏱️ ETA: `{time_formatter(eta)}`"
            )
            
            asyncio.run_coroutine_threadsafe(self.safe_edit(text), loop)

    async def safe_edit(self, text):
        try: await self.msg.edit_text(text)
        except: pass

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 **High-Speed Multi-Worker Downloader Ready**\nSend any valid video or playlist link to begin.")

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
    await message.reply_text("⚡ **Select Quality Preference:**\n_(Asynchronous processing supported)_", reply_markup=InlineKeyboardMarkup(buttons))

async def download_worker(client, url, quality, chat_id, extra_info=""):
    """Download Worker that process chunks, uploads, and purges workspace files cleanly."""
    async with download_semaphore:
        msg = await client.send_message(chat_id, "⏳ `Parsing item details from server...`")
        unique_id = f"{chat_id}_{int(time.time())}"
        
        # Configure High-Speed multi-threaded options for yt-dlp using aria2c
        ydl_opts = {
            'quiet': True,
            'noplaylist': True, 
            'nocheckcertificate': True,
            'external_downloader': 'aria2c',
            'external_downloader_args': ['-x', '16', '-s', '16', '-k', '1M', '--max-connection-per-server=16'],
        }

        try:
            loop_instance = asyncio.get_running_loop()
            
            # 1. Gather Metadata 
            with YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
                info = await loop_instance.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                title = info.get('title', 'video')
                # Strict dynamic naming assignment to avoid collisions
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
                out_tmpl = f"{unique_id}_{safe_title}.%(ext)s"

            if quality == "48k":
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'outtmpl': out_tmpl,
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '48',
                    }],
                })
            else:
                ydl_opts.update({
                    'format': f"bestvideo[height<={quality}]+bestaudio/best",
                    'outtmpl': out_tmpl,
                    'merge_output_format': 'mp4'
                })

            # Hooking dynamic download telemetry tracker
            progress_hook = YtdlProgressHook(client, chat_id, msg, title, extra_info)
            ydl_opts['progress_hooks'] = [progress_hook]

            # 2. Trigger yt-dlp Download Chunks
            with YoutubeDL(ydl_opts) as ydl:
                await loop_instance.run_in_executor(None, lambda: ydl.download([url]))

            # Find matching finalized artifact accurately via wildcard scanning
            downloaded_files = glob.glob(f"{unique_id}_*")
            filename = None
            for file in downloaded_files:
                if not file.endswith('.part') and not file.endswith('.ytdl'):
                    filename = file
                    break
            
            if not filename or not os.path.exists(filename):
                raise FileNotFoundError("Target downloadable file could not be generated cleanly.")

            # 3. Dynamic Upload with Telegram Trackers
            start_time = time.time()
            if quality == "48k":
                await client.send_audio(
                    chat_id, audio=filename, caption=f"🎵 **{title}** [48kbps]",
                    progress=progress_bar, progress_args=(msg, start_time, "Uploading Audio Stream", title, extra_info)
                )
            else:
                await client.send_video(
                    chat_id, video=filename, caption=f"🎬 **{title}** [{quality}p]",
                    progress=progress_bar, progress_args=(msg, start_time, "Uploading Video Stream", title, extra_info)
                )
            await msg.delete()

        except Exception as e:
            try: await msg.edit_text(f"❌ **Error Handling Entry:**\n`{title if 'title' in locals() else 'Unknown'}`\n`{str(e)}`")
            except: pass
        
        finally:
            # Absolute Server Wipe Hook (Deletes all temporary elements, fragments, and final videos)
            for structural_garbage in glob.glob(f"{unique_id}_*"):
                try: os.remove(structural_garbage)
                except: pass

@app.on_callback_query(filters.regex(r"^dl\|"))
async def process_callback(client, query):
    _, quality, url = query.data.split("|")
    chat_id = query.message.chat.id
    await query.answer("Added to multi-worker asynchronous runtime environment...")
    await query.message.delete()

    with YoutubeDL({'extract_flat': True, 'quiet': True}) as ydl:
        meta = ydl.extract_info(url, download=False)
        
    if 'entries' in meta:
        entries = list(meta['entries'])
        total_items = len(entries)
        status_msg = await client.send_message(chat_id, f"📦 **Playlist Detected:** `{total_items}` elements found.\nDeploying Multi-Worker Pool Processors...")
        
        tasks = []
        for index, entry in enumerate(entries, start=1):
            video_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
            extra_info = f"Video {index} of {total_items}"
            tasks.append(download_worker(client, video_url, quality, chat_id, extra_info=extra_info))
        
        await asyncio.gather(*tasks)
        await status_msg.edit(f"✅ **Completed!** All {total_items} playlist elements processed successfully and purged from the host server.")
    else:
        # Process individual stream
        await download_worker(client, url, quality, chat_id, extra_info="Single File Process")

if __name__ == "__main__":
    app.run()

