import os
import requests
import re
from flask import Flask, request, send_from_directory
from datetime import datetime, timedelta
from google import genai
from dotenv import load_dotenv

load_dotenv()

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")
EDITOR_BASE_URL = os.getenv("PUBLIC_BASE_URL") + "/editor"

app = Flask(__name__)

# ===== ログファイル =====
CAMERA_LOG = "/app/summary.txt"
SHARED_LOG = "/app/shared_summary/summary.txt"

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# ==============================
# 共通：日時抽出（両形式対応）
# ==============================
def extract_datetime(line):
    # 形式1: [2026/02/22 22:36:12]
    match1 = re.search(r'\[(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})\]', line)
    if match1:
        return datetime.strptime(match1.group(1), "%Y/%m/%d %H:%M:%S")

    # 形式2: 20260222223612（ファイル名内）
    match2 = re.search(r'(\d{14})', line)
    if match2:
        return datetime.strptime(match2.group(1), "%Y%m%d%H%M%S")

    return None


# ==============================
# 今日のログ取得
# ==============================
def get_today_lines(path):
    if not os.path.exists(path):
        return []

    jst_now = datetime.utcnow() + timedelta(hours=9)
    today = jst_now.date()

    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            dt = extract_datetime(line)
            if dt and dt.date() == today:
                results.append(line.strip())

    return results


# ==============================
# 直近N分のログ取得
# ==============================
def get_recent_lines(lines, minutes=30):
    jst_now = datetime.utcnow() + timedelta(hours=9)
    threshold = jst_now - timedelta(minutes=minutes)

    recent = []
    for l in lines:
        dt = extract_datetime(l)
        if dt and dt >= threshold:
            recent.append(l)

    return recent


# ==============================
# Gemini要約
# ==============================
def get_gemini_summary(log_lines, target_type="今"):
    if not log_lines:
        return "最近の記録はありません。"

    combined_logs = "\n".join(log_lines[-20:])

    prompt = f"""
    猫のハチくんの見守り役として、
    以下のログから「{target_type}の様子」を50文字以内で自然な日本語で要約してください。
    システム語（判定: など）は含めないでください。

    ログ:
    {combined_logs}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt]
        )
        return response.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        return "要約に失敗しました。"


# ==============================
# トイレ回数カウント
# ==============================
def count_events(lines, target_label):

    event_times = []

    if target_label == "poop":
        threshold = timedelta(hours=1)
    else:
        threshold = timedelta(minutes=30)

    for l in lines:
        is_match = False
        if target_label == "pee":
            if "おしっこ" in l:
                is_match = True
        elif target_label == "poop":
            if "うんち" in l or "便" in l:
                is_match = True

        if is_match:
            dt = extract_datetime(l)
            if dt:
                event_times.append(dt)

    if not event_times:
        return 0, []

    event_times.sort()

    count = 0
    last_time = None
    notes = []

    for t in event_times:
        if last_time is None or (t - last_time) > threshold:
            count += 1
            last_time = t
        else:
            notes.append(f"※ {last_time.strftime('%H:%M')}と{t.strftime('%H:%M')}は{int((t - last_time).seconds // 60)}分以内のため1回にまとめました")

    return count, notes


# ==============================
# 体重平均取得
# ==============================
def get_today_weight_average(lines):
    jst_now = datetime.utcnow() + timedelta(hours=9)
    today = jst_now.date()

    weights = []
    for l in lines:
        dt = extract_datetime(l)
        if not dt or dt.date() != today:
            continue

        match = re.search(r'猫体重[:：]\s*(\d+(?:\.\d+)?)g', l)
        if match:
            w = float(match.group(1)) / 1000
            weights.append(w)

    if not weights:
        return None

    return round(sum(weights) / len(weights), 2)


# ==============================
# 編集ボタン送信
# ==============================
def send_edit_button(user_id):
    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "template",
                "altText": "トイレ履歴の編集画面",
                "template": {
                    "type": "buttons",
                    "title": "トイレ履歴の修正",
                    "text": "最近の判定を編集・削除できます🐾",
                    "actions": [
                        {
                            "type": "uri",
                            "label": "編集画面を開く",
                            "uri": EDITOR_BASE_URL
                        }
                    ]
                }
            }
        ]
    }

    try:
        res = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_TOKEN}"
            },
            json=payload,
            timeout=3
        )
        print("Edit push:", res.status_code, res.text)
    except Exception as e:
        print("Edit push error:", e)


# ==============================
# LINE Webhook
# ==============================
@app.route("/callback", methods=['POST'])
def callback():
    body = request.get_json()
    print("Received:", body)

    if not body or "events" not in body or not body["events"]:
        return "OK", 200

    event = body["events"][0]
    reply_token = event.get("replyToken")
    user_id = event.get("source", {}).get("userId")

    if not reply_token or "message" not in event:
        return "OK", 200

    user_msg = event["message"].get("text", "")
    print("User:", user_msg)

    is_toilet = any(k in user_msg for k in ["トイレ", "おしっこ", "うんこ", "便"])
    is_summary = any(k in user_msg for k in ["まとめ", "今日", "報告"])
    is_now = any(k in user_msg for k in ["今", "状況", "なにしてる"])
    is_weight = any(k in user_msg for k in ["体重", "kg", "きろ"])
    is_edit = any(k in user_msg for k in ["編集", "履歴", "修正"])

    print("is_edit =", is_edit)
    print("user_msg =", user_msg)

    if not (is_toilet or is_summary or is_now or is_weight or is_edit):
        return "OK", 200

    # =========================
    # ① まず即返信（超重要）
    # =========================
    try:
        quick_payload = {
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": "ちょっと待っててね🐾 集計中です…"}]
        }
        requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_TOKEN}"
            },
            json=quick_payload,
            timeout=3
        )
    except Exception as e:
        print("Quick reply error:", e)
        return "OK", 200

    # =========================
    # ② 本処理
    # =========================
    jst_now = datetime.utcnow() + timedelta(hours=9)
    avg_weight = None  # push送信ブロックで参照するため先に初期化

    if is_edit:
        send_edit_button(user_id)
        return "OK", 200

    elif is_weight:
        today_lines = get_today_lines(SHARED_LOG)
        avg_weight = get_today_weight_average(today_lines)

        # グラフを最新データで再生成
        try:
            from graph_worker import generate_last_month_weight_graph_from_log
            with open(SHARED_LOG, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            generate_last_month_weight_graph_from_log(all_lines)
            print("Graph regenerated.")
        except Exception as e:
            print("Graph generation error:", e)

        if avg_weight is not None:
            msg = f"今日の体重平均は {avg_weight:.2f} kg です🐾"
        else:
            msg = "今日の体重記録はありません🐾"

    elif is_toilet:
        lines = get_today_lines(SHARED_LOG)
        pee, pee_notes = count_events(lines, "pee")
        poop, poop_notes = count_events(lines, "poop")

        summary = get_gemini_summary(lines, "トイレ周辺")

        notes_str = "\n".join(pee_notes + poop_notes)
        msg = (
            f"【🚽 トイレ情報】\n"
            f"おしっこ: {pee}回\n"
            f"うんち: {poop}回\n"
            f"{notes_str + chr(10) if notes_str else ''}\n"
            f"{summary}"
        )

    elif is_summary:
        lines = get_today_lines(CAMERA_LOG)
        summary = get_gemini_summary(lines, "今日一日")
        msg = f"【今日({jst_now.strftime('%m/%d')})】\n{summary}"

    else:  # is_now
        lines = get_today_lines(CAMERA_LOG)
        recent = get_recent_lines(lines, 30)
        target = recent if recent else lines[-20:]
        summary = get_gemini_summary(target, "今")
        msg = f"【今のハチ】\n{summary}"

    # =========================
    # ③ push送信
    # =========================
    try:
        messages = [{"type": "text", "text": msg}]

        if is_weight and avg_weight is not None:
            image_url = f"{PUBLIC_BASE_URL}/shared_summary/last_month_weight.png"
            print("Image URL =", image_url)
            messages.append({
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url
            })

        push_payload = {
            "to": user_id,
            "messages": messages
        }

        res = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_TOKEN}"
            },
            json=push_payload,
            timeout=5
        )
        print("Push status:", res.status_code, res.text)

    except Exception as e:
        print("Push error:", e)

    return "OK", 200


@app.route("/shared_summary/<path:filename>")
def serve_shared_file(filename):
    """
    /app/shared_summary ディレクトリ内のファイルを配信する。
    画像(last_month_weight.pngなど)を外部からアクセス可能にするために必要。
    """
    return send_from_directory("/app/shared_summary", filename)


@app.route("/editor", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/editor/<path:path>", methods=["GET", "POST"])
def proxy_editor(path):
    target = f"http://label-editor:5056/{path}"
    resp = requests.request(
        method=request.method,
        url=target,
        data=request.get_data(),
        headers={k: v for k, v in request.headers if k != "Host"},
        params=request.args,        # ★追加
        allow_redirects=False
    )
    if resp.status_code in (301, 302):
        location = resp.headers.get("Location", "/")
        # label-editor側の絶対パスを/editor配下に書き換え
        location = "/editor" + location if location.startswith("/") else "/editor"
        return "", resp.status_code, {"Location": location}
    return resp.content, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "text/html")}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
