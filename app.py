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

import anthropic

# ---------------------------------------------------------------------------
# 基本設定
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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

# 若想做多輪對話記憶，可改用資料庫或 Redis 依 user_id 儲存歷史訊息。
# 此版本為單輪問答（每則訊息獨立處理），先求穩定上線，之後可再擴充。

# ---------------------------------------------------------------------------
# 呼叫 Claude API
# ---------------------------------------------------------------------------


def ask_claude(user_message: str) -> str:
    try:
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        # content 是一個 list of blocks，取出文字部分並串接
        reply_text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        return reply_text or "不好意思，這部分目前我沒有相關資料，建議您聯繫窗口人員確認喔。"
    except Exception:
        logger.exception("呼叫 Claude API 失敗")
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
    reply_text = ask_claude(user_message)

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
