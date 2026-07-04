import os
import requests
import re
from flask import Flask, request, send_from_directory
from datetime import datetime, timedelta
from urllib.parse import parse_qs
from google import genai
from dotenv import load_dotenv

load_dotenv()

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
EDITOR_BASE_URL = f"{PUBLIC_BASE_URL}/editor" if PUBLIC_BASE_URL else "/editor"
CAT_SCALE_BASE_URL = os.getenv("CAT_SCALE_BASE_URL", "http://cat-scale:8000").rstrip("/")
MANUAL_EVENT_TOKEN = os.getenv("MANUAL_EVENT_TOKEN", "")
ALEXA_EVENT_TOKEN = os.getenv("ALEXA_EVENT_TOKEN", "")

app = Flask(__name__)

# ===== ログファイル =====
CAMERA_LOG = "/app/summary.txt"
SHARED_LOG = "/app/shared_summary/summary.txt"

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# ==============================
# 共通：日時処理
# ==============================
def jst_now():
    return datetime.utcnow() + timedelta(hours=9)


def line_datetime_value(dt):
    # LINE datetimepicker examples use a lower-case t separator.
    return dt.strftime("%Y-%m-%dt%H:%M")


def manual_event_datetime_value(dt):
    return dt.strftime("%Y/%m/%d %H:%M:%S")


def parse_line_datetime(value):
    value = (value or "").strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dt%H:%M:%S",
        "%Y-%m-%dt%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def parse_time_only(value):
    value = (value or "").strip()
    match = re.search(r'(?<!\d)(\d{1,2})[:：時](\d{1,2})(?:分)?(?!\d)', value)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    now = jst_now()
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def postback_event_time(event):
    params = event.get("postback", {}).get("params", {}) or {}
    if "datetime" in params:
        return parse_line_datetime(params["datetime"])
    if "time" in params:
        return parse_time_only(params["time"])
    if "date" in params:
        try:
            picked = datetime.strptime(params["date"], "%Y-%m-%d")
            now = jst_now()
            return picked.replace(hour=now.hour, minute=now.minute, second=0)
        except ValueError:
            return None
    return None


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
# LINE送信ヘルパー
# ==============================
def line_headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }


def reply_messages(reply_token, messages, timeout=5):
    payload = {"replyToken": reply_token, "messages": messages}
    return requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers=line_headers(),
        json=payload,
        timeout=timeout
    )


def push_messages(user_id, messages, timeout=5):
    payload = {"to": user_id, "messages": messages}
    return requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers=line_headers(),
        json=payload,
        timeout=timeout
    )


# ==============================
# cat_scale手動イベント登録
# ==============================
def manual_event_display(label):
    return {
        "poop": "うんち",
        "pee": "おしっこ",
        "entry_only": "入出のみ",
    }.get(label, label)


def parse_manual_text_command(text):
    label = None
    if any(k in text for k in ["うんち", "うんこ", "便", "poop"]):
        label = "poop"
    elif any(k in text for k in ["おしっこ", "尿", "pee"]):
        label = "pee"
    elif any(k in text for k in ["入出", "入退", "入っただけ", "entry"]):
        label = "entry_only"

    if not label:
        return None, None

    event_time = parse_time_only(text)
    explicit_manual = any(k in text for k in ["にして", "修正", "登録", "記録", "手動"])
    if event_time or explicit_manual:
        return label, event_time
    return None, None


def call_manual_event(label, source="line", event_time=None):
    params = {"label": label, "source": source}
    headers = {}
    if event_time is not None:
        params["datetime"] = manual_event_datetime_value(event_time)
        params["timestamp"] = str(int(event_time.timestamp()))
    if MANUAL_EVENT_TOKEN:
        params["token"] = MANUAL_EVENT_TOKEN
        headers["Authorization"] = f"Bearer {MANUAL_EVENT_TOKEN}"

    url = f"{CAT_SCALE_BASE_URL}/manual_event"
    res = requests.post(url, params=params, headers=headers, timeout=8)
    try:
        body = res.json()
    except Exception:
        body = {"text": res.text}

    if res.status_code >= 400:
        raise RuntimeError(f"{res.status_code}: {body}")
    return body


def immediate_toilet_action_template():
    return {
        "type": "template",
        "altText": "直近のトイレ判定を修正できます",
        "template": {
            "type": "buttons",
            "title": "直近の判定を修正",
            "text": "時刻指定なし。現在時刻で登録します",
            "actions": [
                {
                    "type": "postback",
                    "label": "うんちにする",
                    "data": "action=manual_event&label=poop",
                    "displayText": "今をうんちにする"
                },
                {
                    "type": "postback",
                    "label": "おしっこにする",
                    "data": "action=manual_event&label=pee",
                    "displayText": "今をおしっこにする"
                },
                {
                    "type": "postback",
                    "label": "入出のみにする",
                    "data": "action=manual_event&label=entry_only",
                    "displayText": "今を入出のみにする"
                },
                {
                    "type": "uri",
                    "label": "編集画面を開く",
                    "uri": EDITOR_BASE_URL
                }
            ]
        }
    }


def timed_toilet_action_template():
    now = jst_now()
    min_dt = now - timedelta(days=2)
    max_dt = now + timedelta(minutes=5)
    return {
        "type": "template",
        "altText": "時刻を指定してトイレ判定を登録できます",
        "template": {
            "type": "buttons",
            "title": "時刻指定で登録",
            "text": "日時を選ぶと、その時刻の手動ラベルとして登録します",
            "actions": [
                {
                    "type": "datetimepicker",
                    "label": "うんち時刻指定",
                    "data": "action=manual_event&label=poop",
                    "mode": "datetime",
                    "initial": line_datetime_value(now),
                    "min": line_datetime_value(min_dt),
                    "max": line_datetime_value(max_dt)
                },
                {
                    "type": "datetimepicker",
                    "label": "おしっこ時刻指定",
                    "data": "action=manual_event&label=pee",
                    "mode": "datetime",
                    "initial": line_datetime_value(now),
                    "min": line_datetime_value(min_dt),
                    "max": line_datetime_value(max_dt)
                },
                {
                    "type": "datetimepicker",
                    "label": "入出のみ時刻指定",
                    "data": "action=manual_event&label=entry_only",
                    "mode": "datetime",
                    "initial": line_datetime_value(now),
                    "min": line_datetime_value(min_dt),
                    "max": line_datetime_value(max_dt)
                }
            ]
        }
    }


def toilet_action_templates():
    return [immediate_toilet_action_template(), timed_toilet_action_template()]


def handle_postback(event):
    reply_token = event.get("replyToken")
    data = event.get("postback", {}).get("data", "")
    params = parse_qs(data)
    action = params.get("action", [""])[0]

    if action != "manual_event":
        if reply_token:
            reply_messages(reply_token, [{"type": "text", "text": "未対応の操作です。"}])
        return

    label = params.get("label", [""])[0]
    if label not in {"poop", "pee", "entry_only"}:
        if reply_token:
            reply_messages(reply_token, [{"type": "text", "text": "不明なラベルです。"}])
        return

    event_time = postback_event_time(event)
    try:
        result = call_manual_event(label, source="line_postback", event_time=event_time)
        status = result.get("status", "ok") if isinstance(result, dict) else "ok"
        time_text = manual_event_datetime_value(event_time) if event_time else "現在時刻"
        text = f"{time_text} の記録を「{manual_event_display(label)}」にしました。({status})"
    except Exception as e:
        print("Manual event error:", e)
        text = f"手動ラベルの登録に失敗しました: {e}"

    if reply_token:
        reply_messages(reply_token, [{"type": "text", "text": text}])


# ==============================
# 今日のログ取得
# ==============================


# ==============================
# Alexa manual event endpoint
# ==============================
def alexa_response(text, end_session=True):
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": end_session,
        },
    }


def verify_alexa_token(payload):
    if not ALEXA_EVENT_TOKEN:
        return True
    supplied = request.headers.get("X-Hachi-Token") or request.args.get("token")
    if not supplied and isinstance(payload, dict):
        supplied = payload.get("token")
    return supplied == ALEXA_EVENT_TOKEN


def normalize_manual_label(value):
    text = str(value or "").strip().lower()
    if text in {"poop", "poo", "feces", "stool", "unchi", "unko"}:
        return "poop"
    if text in {"pee", "urine", "oshikko"}:
        return "pee"
    if text in {"entry_only", "entry", "enter", "entered", "only_entry"}:
        return "entry_only"
    return None


def alexa_slot_value(payload, *names):
    try:
        slots = payload.get("request", {}).get("intent", {}).get("slots", {})
        for name in names:
            slot = slots.get(name) or slots.get(name.lower()) or slots.get(name.upper())
            if not slot:
                continue
            resolutions = slot.get("resolutions", {}).get("resolutionsPerAuthority", [])
            for resolution in resolutions:
                values = resolution.get("values") or []
                if values:
                    resolved = values[0].get("value", {})
                    return resolved.get("id") or resolved.get("name")
            if "value" in slot:
                return slot["value"]
    except Exception:
        pass
    return None


def parse_alexa_event(payload):
    payload = payload or {}
    label = normalize_manual_label(
        request.args.get("label")
        or request.form.get("label")
        or payload.get("label")
        or alexa_slot_value(payload, "event_type", "eventType", "label")
    )

    spoken_text = " ".join(
        str(v) for v in [
            request.args.get("text"),
            request.form.get("text"),
            payload.get("text") if isinstance(payload, dict) else None,
        ] if v
    )
    if not label and spoken_text:
        label, _ = parse_manual_text_command(spoken_text)

    time_value = (
        request.args.get("datetime")
        or request.args.get("time")
        or request.form.get("datetime")
        or request.form.get("time")
        or payload.get("datetime")
        or payload.get("time")
        or alexa_slot_value(payload, "time", "event_time", "eventTime")
    )
    event_time = parse_line_datetime(time_value) or parse_time_only(time_value)
    if not event_time and spoken_text:
        event_time = parse_time_only(spoken_text)
    return label, event_time


@app.route("/alexa/manual_event", methods=["GET", "POST"])
def alexa_manual_event():
    payload = request.get_json(silent=True) or {}
    if not verify_alexa_token(payload):
        return alexa_response("Authentication failed."), 403

    alexa_request_type = payload.get("request", {}).get("type") if isinstance(payload, dict) else None
    if alexa_request_type == "LaunchRequest":
        return alexa_response("Hachi toilet is ready. Say poop, pee, or entry only.", end_session=False)

    label, event_time = parse_alexa_event(payload)
    if not label:
        return alexa_response("Please say poop, pee, or entry only.", end_session=False), 400

    try:
        result = call_manual_event(label, source="alexa", event_time=event_time)
        status = result.get("status", "ok") if isinstance(result, dict) else "ok"
        time_text = manual_event_datetime_value(event_time) if event_time else "current time"
        return alexa_response(f"Recorded {manual_event_display(label)} at {time_text}.")
    except Exception as e:
        print("Alexa manual event error:", e)
        return alexa_response("Failed to record the event."), 500

def get_today_lines(path):
    if not os.path.exists(path):
        return []

    today = jst_now().date()

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
    threshold = jst_now() - timedelta(minutes=minutes)

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
    today = jst_now().date()

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
            headers=line_headers(),
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

    if event.get("type") == "postback":
        handle_postback(event)
        return "OK", 200

    if not reply_token or "message" not in event:
        return "OK", 200

    user_msg = event["message"].get("text", "")
    print("User:", user_msg)

    manual_label, manual_time = parse_manual_text_command(user_msg)
    if manual_label:
        try:
            result = call_manual_event(manual_label, source="line_text", event_time=manual_time)
            status = result.get("status", "ok") if isinstance(result, dict) else "ok"
            time_text = manual_event_datetime_value(manual_time) if manual_time else "現在時刻"
            reply_messages(reply_token, [{"type": "text", "text": f"{time_text} の記録を「{manual_event_display(manual_label)}」にしました。({status})"}])
        except Exception as e:
            print("Manual text event error:", e)
            reply_messages(reply_token, [{"type": "text", "text": f"手動ラベルの登録に失敗しました: {e}"}])
        return "OK", 200

    is_toilet = any(k in user_msg for k in ["トイレ", "おしっこ", "うんこ", "うんち", "便"])
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
        reply_messages(reply_token, [{"type": "text", "text": "ちょっと待っててね🐾 集計中です…"}], timeout=3)
    except Exception as e:
        print("Quick reply error:", e)
        return "OK", 200

    # =========================
    # ② 本処理
    # =========================
    now = jst_now()
    avg_weight = None  # push送信ブロックで参照するため先に初期化
    include_toilet_buttons = False

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
        include_toilet_buttons = True

    elif is_summary:
        lines = get_today_lines(CAMERA_LOG)
        summary = get_gemini_summary(lines, "今日一日")
        msg = f"【今日({now.strftime('%m/%d')})】\n{summary}"

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

        if include_toilet_buttons:
            messages.extend(toilet_action_templates())

        if is_weight and avg_weight is not None:
            image_url = f"{PUBLIC_BASE_URL}/shared_summary/last_month_weight.png"
            print("Image URL =", image_url)
            messages.append({
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url
            })

        res = push_messages(user_id, messages, timeout=5)
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
        params=request.args,
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
