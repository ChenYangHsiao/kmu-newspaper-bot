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
    # 不直接 raise，避免 Render 健康檢查失敗時看不到 log
    print("[WARN] LINE_CHANNEL_ACCESS_TOKEN / LINE_CHANNEL_SECRET not set.")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "template.png")

# 合成框座標（請依你的模板）
FRAME_X = 2888
FRAME_Y = 3856
FRAME_W = 2729
FRAME_H = 1874

# 固定輸出檔案
OUTPUT_PATH = os.path.join(BASE_DIR, "output.png")


# -----------------------------
# Helpers
# -----------------------------
def compose_image(user_image_bytes: bytes) -> None:
    """合成後輸出到 OUTPUT_PATH (固定 output.png)"""
    template = Image.open(TEMPLATE_PATH).convert("RGBA")

    user_img = Image.open(BytesIO(user_image_bytes)).convert("RGBA")

    # 依框尺寸做填滿裁切（不變形，必要時裁切）
    user_img = ImageOps.fit(user_img, (FRAME_W, FRAME_H), method=Image.LANCZOS, centering=(0.5, 0.5))

    # 貼到模板
    template.paste(user_img, (FRAME_X, FRAME_Y), user_img)

    # 存檔（PNG）
    template.save(OUTPUT_PATH, format="PNG")


# -----------------------------
# Routes
# -----------------------------
@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route("/output.png", methods=["GET"])
def get_output():
    # 直接回傳最新 output.png
    if not os.path.exists(OUTPUT_PATH):
        return "No output yet", 404
    return send_file(OUTPUT_PATH, mimetype="image/png", conditional=False)


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

        # 2) 合成 output.png
        compose_image(img_bytes)

        # 3) 回傳圖片 URL（加上防快取參數 v=timestamp）
        base_url = os.getenv("RENDER_EXTERNAL_URL", "https://kmu-newspaper-bot-2.onrender.com")
        # 重要：固定路徑 + query string 破除 LINE 快取
        image_url = f"{base_url}/output.png?v={int(time.time())}"

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
    # 保底（避免某些事件進來報錯）
    pass


if __name__ == "__main__":
    # Render 會用 gunicorn 啟動，這段只方便本地測試
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
