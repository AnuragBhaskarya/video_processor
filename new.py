from flask import Flask, request, send_file, jsonify
import os
import yt_dlp
import uuid

app = Flask(__name__)
DOWNLOAD_DIR = "downloads"
COOKIE_PATH = "cookies.txt"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

@app.route('/')
def home():
    return '✅ Instagram Downloader API is running!'

@app.route('/download', methods=['POST'])
def download_instagram_video():
    video_url = request.form.get('url')
    cookies_file = request.files.get('cookies')

    if not video_url or not cookies_file:
        return jsonify({'error': 'Missing URL or cookies.txt file'}), 400

    # Save cookies
    cookies_file.save(COOKIE_PATH)

    # Unique filename
    unique_id = str(uuid.uuid4())
    output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}.%(ext)s")

    # yt-dlp options
    ydl_opts = {
        'outtmpl': output_path,
        'cookiefile': COOKIE_PATH,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'quiet': True,
        'noplaylist': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            file_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}.{info['ext']}")
            return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)