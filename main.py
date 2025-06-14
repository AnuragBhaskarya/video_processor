import os
import subprocess
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from yt_dlp import YoutubeDL
import uuid
from flask import Flask, request, jsonify
import threading
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
import requests
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MY_CHAT_ID = os.getenv("MY_CHAT_ID")

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=3)

# Download video using yt-dlp
def download_video(url, download_path):
    ydl_opts = {
        'outtmpl': download_path,
        'format': 'bestvideo+bestaudio/best',
        'quiet': True,
        'merge_output_format': 'mp4',
        'cookies': 'cookies.txt'
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

# Process video with FFmpeg
def process_video(input_path, output_path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', input_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        duration = float(result.stdout.strip())
        trim_duration = duration - 0.5
        if trim_duration <= 0:
            raise ValueError("Video too short to trim 0.5s")

        crop_offset = 300
        speed = 1.1
        pitch_factor = 1.05

        filter_complex = (
            f"[0:v]crop=in_w:if(gte(in_h\\,{crop_offset})\\,in_h-{crop_offset}\\,in_h):0:if(gte(in_h\\,{crop_offset})\\,{crop_offset}/2\\,0),"
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "gblur=sigma=15[bg];"
            f"[0:v]crop=in_w:if(gte(in_h\\,{crop_offset})\\,in_h-{crop_offset}\\,in_h):0:if(gte(in_h\\,{crop_offset})\\,{crop_offset}/2\\,0),"
            "noise=alls=10:allf=t+u,"
            "scale=w='if(gte(iw/ih,1080/1920),1080,-1)':h='if(gte(iw/ih,1080/1920),-1,1920)',"
            "scale=iw*0.90:ih*0.90[main];"
            "[bg][main]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2[with_main];"
            f"[with_main]setpts=PTS/{speed},"
            "format=yuv444p,"
            "format=yuv420p[v];"
            f"[0:a]asetrate=44100*{pitch_factor},aresample=44100,atempo={speed}[a]"
        )

        command = [
            'ffmpeg',
            '-r', '29.97',
            '-i', input_path,
            '-filter_complex', filter_complex,
            '-map', '[v]',
            '-map', '[a]',
            '-ss', '0',
            '-t', str(trim_duration),
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-map_metadata', '-1',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]

        subprocess.run(command, capture_output=True, text=True, check=True)
    except Exception as e:
        logging.error(f"FFmpeg processing failed: {e}")
        raise

# Telegram message
def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {'chat_id': MY_CHAT_ID, 'text': text}
        requests.post(url, json=data, timeout=30).raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Failed to send message: {e}")
        return False

# Send Telegram video
def send_telegram_video(video_path):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        with open(video_path, 'rb') as video_file:
            files = {'video': video_file}
            requests.post(url, data={'chat_id': MY_CHAT_ID}, files=files, timeout=120).raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Failed to send video: {e}")
        return False

# Combined flow
def process_and_send_video_sync(instagram_url, source="API"):
    send_telegram_message(f'🔥 Processing your video from {source}...\nURL: {instagram_url}')
    unique_id = str(uuid.uuid4())
    download_path = f'{unique_id}.mp4'
    processed_path = f'{unique_id}_processed.mp4'

    try:
        download_video(instagram_url, download_path)
        process_video(download_path, processed_path)
        if send_telegram_video(processed_path):
            send_telegram_message('✅ Done! Video processed successfully.')
        else:
            send_telegram_message('⚠️ Video processed but failed to send.')
    except Exception as e:
        send_telegram_message(f'⚠️ An error occurred: {str(e)}')
    finally:
        for file_path in [download_path, processed_path]:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as cleanup_error:
                    logging.error(f"Cleanup failed: {cleanup_error}")

# Flask endpoints
@app.route('/process_instagram', methods=['GET', 'POST'])
def api_process_instagram():
    if request.method == 'POST':
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'Missing Instagram URL in request'}), 400
        instagram_url = data['url']

    elif request.method == 'GET':
        instagram_url = request.args.get('url')
        if not instagram_url:
            return jsonify({'error': 'Missing Instagram URL parameter'}), 400

    else:
        return jsonify({'error': 'Invalid request method'}), 405

    if not instagram_url.startswith('http'):
        return jsonify({'error': 'Invalid Instagram URL format'}), 400

    # Process in background thread
    executor.submit(process_and_send_video_sync, instagram_url, f"API-{request.method}")
    
    return jsonify({'message': 'Video processing started successfully'}), 200

@app.route('/healthz', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time()
    }), 200

# Telegram bot commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to InstaCropBot!\nSend an Instagram video URL to process."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith('http'):
        await update.message.reply_text("Invalid URL")
        return

    await update.message.reply_text("🔥 Processing your video...")
    process_and_send_video_sync(url, "Telegram")

# Run Flask in thread
def run_flask_app():
    app.run(host='0.0.0.0', port=5000)

# Main bot logic
def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    threading.Thread(target=run_flask_app, daemon=True).start()
    application.run_polling()

if __name__ == '__main__':
    main()
