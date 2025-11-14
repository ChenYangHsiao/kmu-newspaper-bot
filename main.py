from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, ImageMessage, TextSendMessage, ImageSendMessage

from PIL import Image
import urllib.request
import os

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 你的模板檔案名稱
TEMPLATE_PATH = "template.png"

# ★ 你的透明框座標（請依照實際模板調整）
FRAME_X = 2888
FRAME_Y = 3856
FRAME_W = 2729
FRAME_H = 1874


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    # STEP 1: 下載使用者照片
    message_id = event.message.id
    message_content = line_bot_api.get_message_content(message_id)

    user_image_path = "user.jpg"
    with open(user_image_path, 'wb') as fd:
        for chunk in message_content.iter_content():
            fd.write(chunk)

    # STEP 2: 打開模板與使用者照片
    template = Image.open(TEMPLATE_PATH).convert("RGBA")
    user_img = Image.open(user_image_path).convert("RGBA")

    # STEP 3: 將照片調整成框大小
    user_img = user_img.resize((FRAME_W, FRAME_H))

    # STEP 4: 貼到透明框位置
    template.paste(user_img, (FRAME_X, FRAME_Y), user_img)

    # STEP 5: 儲存合成檔
    output_path = "output.png"
    template.save(output_path)

    # STEP 6: 回傳圖片給使用者
    image_url = request.url_root + output_path
    line_bot_api.reply_message(
        event.reply_token,
        ImageSendMessage(original_content_url=image_url,
                         preview_image_url=image_url)
    )


@app.route("/output.png")
def serve_output():
    return open("output.png", "rb").read()


@app.route("/")
def index():
    return "KMU Newspaper Bot Running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
