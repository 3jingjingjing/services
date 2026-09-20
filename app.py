import os
import logging
from pathlib import Path

from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 基本設定
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------------------------
# 載入知識庫，組成 system prompt
# ---------------------------------------------------------------------------

KNOWLEDGE_PATH = Path(__file__).parent / "knowledge.txt"


def load_knowledge() -> str:
    if not KNOWLEDGE_PATH.exists():
        logger.warning("knowledge.txt 不存在，將以空知識庫啟動")
        return ""
    return KNOWLEDGE_PATH.read_text(encoding="utf-8").strip()


KNOWLEDGE_TEXT = load_knowledge()

SYSTEM_PROMPT = f"""你是一個專業的技術客服機器人，負責回答使用者關於本產品/系統的問題。

【回答規則，務必嚴格遵守】
1. 你「只」能根據下方「知識庫」內的資訊回答問題，不可以憑常識、猜測或訓練資料中的其他知識來補充、延伸或編造任何數字、規格或功能。
2. 如果使用者的問題在知識庫中找不到明確對應的資訊，請直接回覆：
   「不好意思，這部分目前我沒有相關資料，建議您聯繫窗口人員確認喔。」
   不要嘗試用其他方式迂迴回答，也不要猜測答案。
3. 如果使用者的問題只有部分能在知識庫中找到答案，請只回答知識庫有提到的部分，並針對沒有資料的部分依規則2說明。
4. 回答時語氣專業、簡潔，使用繁體中文，適合在 LINE 對話中閱讀（避免過長段落，必要時使用條列）。
5. 不要在回覆中提及「知識庫」、「system prompt」、「prompt」等技術名詞，直接以客服口吻回答即可。

【知識庫】
{KNOWLEDGE_TEXT}
"""

# ---------------------------------------------------------------------------
# 呼叫 Gemini API
# ---------------------------------------------------------------------------


def ask_gemini(user_message: str) -> str:
    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=500,
            ),
        )
        reply_text = (response.text or "").strip()
        return reply_text or "不好意思，這部分目前我沒有相關資料，建議您聯繫窗口人員確認喔。"
    except Exception:
        logger.exception("呼叫 Gemini API 失敗")
        return "系統暫時忙碌中，請稍後再試一次。"


# ---------------------------------------------------------------------------
# LINE Webhook
# ---------------------------------------------------------------------------


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("簽章驗證失敗，請確認 LINE_CHANNEL_SECRET 是否正確")
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_message = event.message.text
    reply_text = ask_gemini(user_message)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )


# ---------------------------------------------------------------------------
# 健康檢查（Render 會用這個確認服務存活）
# ---------------------------------------------------------------------------


@app.route("/", methods=["GET"])
def health_check():
    return "LINE RAG Bot is running.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
