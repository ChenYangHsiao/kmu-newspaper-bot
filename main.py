import os
import time
from io import BytesIO
from PIL import Image, ImageOps
from flask import Flask, request, abort, send_file

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, ImageMessage, TextSendMessage, ImageSendMessage

# -----------------------------
# Config
# -----------------------------
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    print("[WARN] LINE_CHANNEL_ACCESS_TOKEN / LINE_CHANNEL_SECRET not set.")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "template.png")

# 合成框座標（請依你的模板）
FRAME_X = 60
FRAME_Y = 652
FRAME_W = 878
FRAME_H = 612

# 每次輸出到 outputs/ 之下
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# -----------------------------
# Helpers
# -----------------------------
def compose_image_to_file(user_image_bytes: bytes) -> str:
    """合成後存成 outputs/output_<timestamp>.png，回傳檔名"""
    template = Image.open(TEMPLATE_PATH).convert("RGBA")
    user_img = Image.open(BytesIO(user_image_bytes)).convert("RGBA")

    # 依框尺寸做填滿裁切（不變形，必要時裁切）
    user_img = ImageOps.fit(user_img, (FRAME_W, FRAME_H), method=Image.LANCZOS, centering=(0.5, 0.5))

    # 貼到模板
    template.paste(user_img, (FRAME_X, FRAME_Y), user_img)

    # 用 timestamp 命名，避免快取
    ts = int(time.time() * 1000)
    filename = f"output_{ts}.png"
    out_path = os.path.join(OUTPUT_DIR, filename)

    template.save(out_path, format="PNG")
    return filename


def cleanup_old_outputs(max_files: int = 30):
    """避免磁碟被塞爆：只保留最新 max_files 張"""
    try:
        files = [f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".png")]
        files = sorted(files, key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)), reverse=True)
        for f in files[max_files:]:
            try:
                os.remove(os.path.join(OUTPUT_DIR, f))
            except Exception:
                pass
    except Exception:
        pass


# -----------------------------
# Routes
# -----------------------------
@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route("/outputs/<path:filename>", methods=["GET"])
def serve_output(filename):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        return "Not found", 404
    return send_file(file_path, mimetype="image/png", conditional=False)


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK", 200


# -----------------------------
# LINE Handlers
# -----------------------------
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    try:
        # 1) 抓 LINE 圖片內容
        message_id = event.message.id
        content = line_bot_api.get_message_content(message_id)
        img_bytes = content.content

        # 2) 合成並輸出到 outputs/output_<timestamp>.png
        filename = compose_image_to_file(img_bytes)

        # 3) 清理舊檔（防止爆容量）
        cleanup_old_outputs(max_files=30)

        # 4) 回傳圖片 URL（不同檔名，本身就不會快取）
        base_url = os.getenv("RENDER_EXTERNAL_URL", "https://kmu-newspaper-bot-2.onrender.com")
        image_url = f"{base_url}/outputs/{filename}"

        line_bot_api.reply_message(
            event.reply_token,
            ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            )
        )

    except Exception as e:
        print("[ERROR] handle_image_message:", repr(e))
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="圖片生成失敗，請稍後再試一次。")
        )


@handler.add(MessageEvent, message=None)
def handle_other(event):
    pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
