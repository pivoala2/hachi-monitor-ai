import os, requests, re
from flask import Flask, request
from datetime import datetime, timedelta

app = Flask(__name__)
SUMMARY_FILE = "/app/summary.txt"
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

KEYWORDS_NOW = ["今", "いま", "状況", "様子"]
KEYWORDS_SUMMARY = ["まとめ", "報告", "履歴", "今日"]

def clean_text(text):
    return text.replace("判定:", "").replace("理由:", "").replace("なし", "異常なし")

def parse_log_time(line):
    """
    [Living Room_..._20260118123328.jpg] と 2026-01-18 12:33:28 の両方に対応
    """
    try:
        # 形式1: [Living Room_..._20260118123328.jpg] から数字14桁を抽出
        match = re.search(r'(\d{14})', line)
        if match:
            return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        
        # 形式2: 2026-01-18 12:33:28
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
    except:
        return None

@app.route("/callback", methods=['POST'])
def callback():
    body = request.get_json()
    if not body or 'events' not in body or len(body['events']) == 0:
        return "OK", 200

    event = body['events'][0]
    reply_token = event.get('replyToken')
    user_message = event.get('message', {}).get('text', "")

    is_now = any(k in user_message for k in KEYWORDS_NOW)
    is_summary = any(k in user_message for k in KEYWORDS_SUMMARY)

    if not (is_now or is_summary):
        return "OK", 200

    if not os.path.exists(SUMMARY_FILE):
        message_text = "記録ファイルが見つかりません。"
    else:
        with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]

        jst_now = datetime.utcnow() + timedelta(hours=9)

        if is_summary:
            today_hyphen = jst_now.strftime('%Y-%m-%d')
            today_compact = jst_now.strftime('%Y%m%d')
            
            # おしっこ、うんこ、エサの記録を抽出
            important_logs = [clean_text(l) for l in lines if (today_hyphen in l or today_compact in l) and any(x in l for x in ["おしっこ", "うんこ", "エサ"])]
            
            if important_logs:
                message_text = f"【今日({today_hyphen})のまとめ】\n" + "\n".join(important_logs[-15:])
            else:
                message_text = f"今日({today_hyphen})はまだ記録がありません。"

        else:
            # 直近30分のログを抽出
            threshold = jst_now - timedelta(minutes=30)
            recent = []
            for l in lines:
                log_time = parse_log_time(l)
                if log_time and log_time >= threshold:
                    recent.append(clean_text(l))
            
            if recent:
                recent.reverse()
                message_text = "【ハチの直近30分】\n" + "\n".join(recent[:10])
            else:
                last_line = lines[-1] if lines else "記録なし"
                message_text = f"直近30分は特に動きがないようです。\n\n【最新の記録】\n{clean_text(last_line)}"

    # LINE返信
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": message_text}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)

    return "OK", 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050)
