import os
import io
import re
from google import genai
from google.genai import types
from PIL import Image
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
IMAGE_DIR = os.getenv("IMAGE_DIR", "/images")
SUMMARY_FILE = "/app/summary.txt"

def parse_time(filename):
    match = re.search(r'(\d{14})', filename)
    if match: return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    return None

def process_batch():
    files = sorted([f for f in os.listdir(IMAGE_DIR) if f.endswith(".jpg")])
    if len(files) < 2: return

    print(f"解析開始: {len(files)}枚を実況中継モードで解析します。")

    for i in range(1, len(files)):
        curr_file = files[i]
        prev_path = os.path.join(IMAGE_DIR, files[i-1])
        curr_path = os.path.join(IMAGE_DIR, curr_file)

        try:
            print(f"解析中: {curr_file}...", end=" ", flush=True)
            
            def get_part(p):
                with Image.open(p) as img:
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format='JPEG')
                    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")

            # プロンプトを「実況中継」に変更
            prompt = """
            あなたは猫のハチくんの生活を記録する専門家です。
            2枚の画像を比較して、以下の項目を「必ず」詳しく記述してください。
            「異常なし」という言葉は使わないでください。

            1. 猫の位置と動き: (例: トイレの縁に足をかけている、中央で寝ている、画面外へ移動中など)
            2. 右下の砂の状態: (例: 1枚目より中央が盛り上がった、変化なし、掘られた跡があるなど)
            3. エサ皿(中央下): (例: 粒が減っている、猫が顔を突っ込んでいる、変化なしなど)

            判定: [おしっこ/エサ/日常] のいずれか1つ
            詳細: (上記3点を踏まえ、20文字以上で実況してください)
            """
            
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[get_part(prev_path), get_part(curr_path), prompt]
            )
            res = response.text.strip().replace("\n", " ")

            with open(SUMMARY_FILE, "a") as f:
                f.write(f"[{curr_file}] {res}\n")
            
            print("完了")

        except Exception as e:
            print(f"エラー: {e}")

    print("全件解析完了。")

if __name__ == "__main__":
    process_batch()
