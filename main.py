import os
from io import BytesIO

from flask import Flask, request, abort, send_file
from PIL import Image

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    ImageMessage,
    ImageSendMessage,
)

# ========= 基本設定 =========
app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

if CHANNEL_ACCESS_TOKEN is None or CHANNEL_SECRET is None:
    raise ValueError("請在 Render 環境變數中設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

TEMPLATE_PATH = "template.png"
OUTPUT_PATH = "output.png"

# ★ 這是依照你 template.png 自動抓出的相框位置（左上 X, 左上 Y, 寬, 高）
FRAME_X = 45
FRAME_Y = 645
FRAME_W = 905
FRAME_H = 628


# ========= 影像合成函式 =========
def compose_image(user_image_bytes: BytesIO, output_path: str = OUTPUT_PATH) -> None:
    """把使用者照片貼到模板的黑色框裡，存成 output.png"""

    # 讀取模板與使用者圖片
    template = Image.open(TEMPLATE_PATH).convert("RGBA")
    user_img = Image.open(user_image_bytes).convert("RGBA")

    # 依照相框比例進行「等比例縮放 + 置中裁切」
    frame_ratio = FRAME_W / FRAME_H
    w, h = user_img.size
    img_ratio = w / h

    if img_ratio > frame_ratio:
        # 圖太寬 -> 以高度對齊，再裁左右
        new_h = FRAME_H
        new_w = int(new_h * img_ratio)
    else:
        # 圖太高 -> 以寬度對齊，再裁上下
        new_w = FRAME_W
        new_h = int(new_w / img_ratio)

    user_resized = user_img.resize((new_w, new_h), Image.LANCZOS)

    # 置中裁切成相框大小
    left = (new_w - FRAME_W) // 2
    top = (new_h - FRAME_H) // 2
    right = left + FRAME_W
    bottom = top + FRAME_H
    user_cropped = user_resized.crop((left, top, right, bottom))

    # 貼到模板上
    template.paste(user_cropped, (FRAME_X, FRAME_Y))

    # 輸出 PNG
    template.save(output_path, format="PNG")


# ========= Flask Routes =========
@app.route("/", methods=["GET"])
def index():
    return "KMU Newspaper Bot is running."


@app.route("/callback", methods=["POST"])
def callback():
    # 取得 X-Line-Signature header
    signature = request.headers.get("X-Line-Signature", "")

    # 取得 request body
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@app.route("/output.png", methods=["GET"])
def get_output():
    if not os.path.exists(OUTPUT_PATH):
        abort(404)
    return send_file(OUTPUT_PATH, mimetype="image/png")


# ========= LINE Bot 事件處理 =========
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event: MessageEvent):
    text = event.message.text.strip()

    # 簡單教學訊息
    reply = (
        "嗨～這是 KMU Spring Banquet 新聞封面小幫手 👋\n\n"
        "請直接傳一張『清楚的人像照片』給我，\n"
        "我會幫你合成在 Breaking News 海報裡！"
    )

    if text in ["hi", "Hi", "哈囉", "嗨", "hello", "Hello"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply),
        )


@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event: MessageEvent):
    """收到圖片時，下載 -> 合成 -> 回傳 output.png"""
    try:
        message_id = event.message.id

        # 從 LINE 把原始圖片抓下來
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = BytesIO()
        for chunk in message_content.iter_content():
            image_bytes.write(chunk)
        image_bytes.seek(0)

        # 執行合成
        compose_image(image_bytes, OUTPUT_PATH)

        # 建立 output.png 的完整網址（給 LINE 顯示圖片用）
        base_url = request.url_root.rstrip("/")  # e.g. https://kmu-newspaper-bot-2.onrender.com
        image_url = f"{base_url}/output.png"

        # 回傳圖片訊息
        image_message = ImageSendMessage(
            original_content_url=image_url,
            preview_image_url=image_url,
        )
        line_bot_api.reply_message(event.reply_token, image_message)

    except Exception as e:
        # 任何錯誤都回覆文字方便你除錯
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"抱歉，合成時發生錯誤：{e}"),
        )


# ========= Render / gunicorn 入口 =========
if __name__ == "__main__":
    # 本地測試用（Render 上會用 gunicorn main:app）
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
