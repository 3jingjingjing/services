"""
評估腳本：驗證 LINE Bot 回答的正確性
------------------------------------------------
用法：
    python eval/run_eval.py

會讀取 eval/test_questions.json 裡的題目，對每一題呼叫跟 app.py
完全相同的 SYSTEM_PROMPT + Gemini 模型設定，然後依題目類型檢查：

  - in_scope（知識庫裡有答案的問題）
      → 回覆必須包含 must_include 指定的關鍵字，且不能觸發拒絕話術
      → 沒包含到關鍵字 = 「答錯／答不完整」
      → 觸發了拒絕話術 = 「誤拒絕」（本來有資料卻說不知道）

  - out_of_scope（知識庫沒有涵蓋的問題，故意問來測試會不會亂編）
      → 回覆必須觸發拒絕話術
      → 沒有觸發 = 「幻覺」（本來該說不知道，卻自己編了答案）

跑完之後會印出總表，並把逐題結果存成 eval/results.json，方便你之後
比對不同版本 prompt 或不同模型的表現。
"""

import json
import os
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 路徑與基本設定（沿用跟 app.py 同一份 knowledge.txt，確保測的是同一套邏輯）
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent
KNOWLEDGE_PATH = ROOT / "knowledge.txt"
QUESTIONS_PATH = Path(__file__).parent / "test_questions.json"
RESULTS_PATH = Path(__file__).parent / "results.json"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

if not GEMINI_API_KEY:
    print("錯誤：請先設定環境變數 GEMINI_API_KEY 再執行這支腳本。")
    sys.exit(1)

# 這句話要跟 app.py 裡拒絕話術的「判斷用關鍵片段」保持一致
# 用片段比對而不是完全相等，是因為模型偶爾用字會有些微差異
REFUSAL_MARKER = "沒有相關資料"

client = genai.Client(api_key=GEMINI_API_KEY)


def load_knowledge() -> str:
    return KNOWLEDGE_PATH.read_text(encoding="utf-8").strip()


def build_system_prompt(knowledge_text: str) -> str:
    # 與 app.py 的 SYSTEM_PROMPT 保持完全一致，避免測的跟正式環境不是同一套規則
    return f"""你是一個專業的技術客服機器人，負責回答使用者關於本產品/系統的問題。

【回答規則，務必嚴格遵守】
1. 你「只」能根據下方「知識庫」內的資訊回答問題，不可以憑常識、猜測或訓練資料中的其他知識來補充、延伸或編造任何數字、規格或功能。
2. 如果使用者的問題在知識庫中找不到明確對應的資訊，請直接回覆：
   「不好意思，這部分目前我沒有相關資料，建議您聯繫窗口人員確認喔。」
   不要嘗試用其他方式迂迴回答，也不要猜測答案。
3. 如果使用者的問題只有部分能在知識庫中找到答案，請只回答知識庫有提到的部分，並針對沒有資料的部分依規則2說明。
4. 回答時語氣專業、簡潔，使用繁體中文，適合在 LINE 對話中閱讀（避免過長段落，必要時使用條列）。
5. 不要在回覆中提及「知識庫」、「system prompt」、「prompt」等技術名詞，直接以客服口吻回答即可。

【知識庫】
{knowledge_text}
"""


def ask(system_prompt: str, question: str) -> str:
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=question,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=500,
        ),
    )
    return (response.text or "").strip()


def evaluate_one(system_prompt: str, item: dict) -> dict:
    question = item["question"]
    q_type = item["type"]

    reply = ask(system_prompt, question)
    refused = REFUSAL_MARKER in reply

    result = {
        "id": item["id"],
        "question": question,
        "type": q_type,
        "reply": reply,
        "refused": refused,
    }

    if q_type == "in_scope":
        must_include = item.get("must_include", [])
        missing = [kw for kw in must_include if kw not in reply]
        if refused:
            result["verdict"] = "false_refusal"  # 誤拒絕：明明有資料卻說不知道
        elif missing:
            result["verdict"] = "incorrect"  # 答錯或答不完整
            result["missing_keywords"] = missing
        else:
            result["verdict"] = "correct"

    elif q_type == "out_of_scope":
        if refused:
            result["verdict"] = "correct"
        else:
            result["verdict"] = "hallucination"  # 幻覺：該說不知道卻自己編答案

    else:
        result["verdict"] = "unknown_type"

    return result


def main():
    knowledge_text = load_knowledge()
    system_prompt = build_system_prompt(knowledge_text)
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))

    results = []
    for i, item in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] 測試中：{item['question']}")
        result = evaluate_one(system_prompt, item)
        results.append(result)
        print(f"    → 判定：{result['verdict']}")
        time.sleep(1)  # 避免打太快撞到 rate limit

    RESULTS_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---------------------------------------------------------------------
    # 統計報告
    # ---------------------------------------------------------------------
    in_scope_results = [r for r in results if r["type"] == "in_scope"]
    out_scope_results = [r for r in results if r["type"] == "out_of_scope"]

    correct_in_scope = sum(1 for r in in_scope_results if r["verdict"] == "correct")
    false_refusals = sum(1 for r in in_scope_results if r["verdict"] == "false_refusal")
    incorrect = sum(1 for r in in_scope_results if r["verdict"] == "incorrect")

    correct_out_scope = sum(1 for r in out_scope_results if r["verdict"] == "correct")
    hallucinations = sum(1 for r in out_scope_results if r["verdict"] == "hallucination")

    print("\n" + "=" * 50)
    print("評估報告")
    print("=" * 50)

    if in_scope_results:
        print(
            f"【範圍內問題】共 {len(in_scope_results)} 題\n"
            f"  正確回答：{correct_in_scope} 題\n"
            f"  答錯/不完整：{incorrect} 題\n"
            f"  誤拒絕（本該有答案卻說不知道）：{false_refusals} 題\n"
            f"  正確率：{correct_in_scope / len(in_scope_results):.0%}"
        )

    if out_scope_results:
        print(
            f"\n【範圍外問題】共 {len(out_scope_results)} 題\n"
            f"  正確拒絕：{correct_out_scope} 題\n"
            f"  幻覺（自己編答案）：{hallucinations} 題\n"
            f"  拒絕正確率：{correct_out_scope / len(out_scope_results):.0%}"
        )

    print(f"\n逐題結果已存到：{RESULTS_PATH}")

    # 有幻覺或誤拒絕，非零結束碼方便串接 CI
    if false_refusals > 0 or hallucinations > 0:
        print("\n⚠️  有題目沒有通過，建議檢查 results.json 並調整 SYSTEM_PROMPT。")
        sys.exit(1)


if __name__ == "__main__":
    main()
