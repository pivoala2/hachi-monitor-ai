import os, io, re, time
from google import genai
from google.genai import types
from PIL import Image
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
IMAGE_DIR = os.getenv("IMAGE_DIR", "/images")
SUMMARY_FILE = "/app/summary.txt"

# 二重解析防止用のフラグ
LAST_PROCESSED_FILE = None

def get_part(p):
    with Image.open(p) as img:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format='JPEG')
        return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")

def get_last_event_time(event_name):
    if not os.path.exists(SUMMARY_FILE): return None
    try:
        with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
            # 判定ラベルを厳密に探す
            lines = [l for l in f.readlines() if f"判定: [{event_name}]" in l]
            if not lines: return None
            match = re.search(r'(\d{14})', lines[-1])
            if match:
                return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    except: pass
    return None

def analyze_latest():
    global LAST_PROCESSED_FILE

    files = sorted([f for f in os.listdir(IMAGE_DIR) if f.endswith(".jpg")])
    if len(files) < 2:
        return

    curr_file = files[-1]
    if curr_file == LAST_PROCESSED_FILE:
        return

    prev_path = os.path.join(IMAGE_DIR, files[-2])
    curr_path = os.path.join(IMAGE_DIR, curr_file)

    prompt = """
    猫のハチくんの見守りAIです。
    2枚の画像を比較して、現在の様子を自然な日本語で説明してください。

    ・動き
    ・居場所
    ・行動の変化
    ・雰囲気

    30〜80文字で簡潔にまとめてください。
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[get_part(prev_path), get_part(curr_path), prompt]
        )

        res = response.text.strip().replace("\n", " ")

        now_str = datetime.now().strftime("%Y%m%d%H%M%S")

        with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
            f.write(f"{now_str} {res}\n")

        LAST_PROCESSED_FILE = curr_file
        print(f"Processed: {curr_file}")

    except Exception as e:
        print("Error:", e)

def generate_daily_summary():
    if not os.path.exists(SUMMARY_FILE):
        return "データがありません"

    today_str = datetime.now().strftime("%Y%m%d")

    lines = []
    with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(today_str):
                lines.append(line.strip())

    if not lines:
        return "今日はまだ記録がありません"

    joined = "\n".join(lines)

    prompt = f"""
    以下は今日の猫ハチくんの行動ログです。

    {joined}

    これを元に、今日一日の様子を200文字以内でまとめてください。
    """

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt
    )

    return response.text.strip()

def prune_log():
    if not os.path.exists(SUMMARY_FILE):
        return

    cutoff = datetime.now() - timedelta(days=30)

    keep_lines = []
    archive_lines = []

    with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            match = re.match(r"(\d{14})", line)
            if not match:
                continue

            line_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")

            if line_time >= cutoff:
                keep_lines.append(line)
            else:
                archive_lines.append(line)

    # アーカイブ保存
    if archive_lines:
        archive_file = "/app/archive_" + datetime.now().strftime("%Y%m") + ".log"
        with open(archive_file, "a", encoding="utf-8") as f:
            f.writelines(archive_lines)

    # 最新1ヶ月だけ残す
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.writelines(keep_lines)

if __name__ == "__main__":
    while True:
        analyze_latest()
        prune_log()  # ← 追加
        time.sleep(300)
