# LINE Bot × Claude API（知識庫限定回答版）

## 專案結構

```
linebot-rag/
├── app.py              # 主程式（Flask webhook + Claude API）
├── knowledge.txt        # 知識庫內容，之後要更新規格就改這個檔案
├── requirements.txt      # Python 套件需求
├── .env.example          # 環境變數範例
└── render.yaml            # Render 部署設定（選用）
```

## 本機測試

1. 安裝套件
   ```bash
   pip install -r requirements.txt
   ```

2. 複製 `.env.example` 為 `.env`，填入你的金鑰（本機測試可用 `python-dotenv` 或直接 `export`）

3. 啟動服務
   ```bash
   python app.py
   ```

4. 由於 LINE Webhook 需要 HTTPS 公開網址，本機測試建議搭配 [ngrok](https://ngrok.com/)：
   ```bash
   ngrok http 5000
   ```
   把 ngrok 給的網址（例如 `https://xxxx.ngrok-free.app/callback`）填到 LINE Developers 後台的 Webhook URL。

## 部署到 Render

1. 把這個資料夾推上 GitHub repo。

2. 到 [Render Dashboard](https://dashboard.render.com/) → **New** → **Web Service**，選擇你的 repo。
   - 若你有推 `render.yaml`，Render 會自動帶入設定；否則手動填：
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `gunicorn app:app`

3. 在 Render 的 **Environment** 分頁新增以下環境變數：
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `LINE_CHANNEL_SECRET`
   - `ANTHROPIC_API_KEY`
   - `CLAUDE_MODEL`（選填，預設 `claude-sonnet-5`）

4. 部署完成後，Render 會給你一個網址，例如 `https://linebot-rag.onrender.com`。

5. 到 [LINE Developers Console](https://developers.line.biz/console/) → 你的 Channel → **Messaging API** 分頁：
   - Webhook URL 填入 `https://linebot-rag.onrender.com/callback`
   - 打開「Use webhook」
   - 建議關閉「Auto-reply messages」與「Greeting messages」（避免LINE官方預設訊息干擾）

6. 用手機掃描 QR Code 加好友，開始測試。

## 「不知道就回不知道」是怎麼實作的

在 `app.py` 的 `SYSTEM_PROMPT` 裡，明確要求 Claude：
- 只能根據 `knowledge.txt` 的內容回答
- 找不到答案時，固定回覆一句制式話術，而不是自由發揮或猜測

這個做法的效果高度依賴 prompt 寫得夠明確。如果之後發現偶爾還是會「腦補」，可以：
1. 把規則寫得更直接、加上具體反例（few-shot）
2. 降低 `temperature`（目前程式碼沒有特別設定，預設值即可，若要更保守可在 `messages.create()` 加入 `temperature=0`）
3. 資料量變大之後改用真正的向量檢索（RAG），只把「檢索到的片段」放進 context，而不是整包知識庫，這樣模型更難跳脫範圍回答

## 之後想擴充的方向

- **多輪對話記憶**：目前每則訊息都是獨立問答，若要記得上下文，需要依 `user_id` 儲存歷史訊息（可用 Render 的 Redis add-on 或簡單的記憶體dict，但記憶體dict在服務重啟或多實例部署時會遺失）。
- **更新知識庫**：直接改 `knowledge.txt` 內容，Render 重新部署（push新commit）即可生效，不用改程式碼。
- **資料量變大**：改用向量資料庫（如 Chroma、pgvector）做真正的檢索，避免system prompt過長增加成本與延遲。
