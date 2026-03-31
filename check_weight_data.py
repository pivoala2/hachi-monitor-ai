from datetime import datetime, timedelta
import re

# 例: 共有ログパス
SHARED_LOG = "/app/shared_summary/summary.txt"

# 過去30日の日付リスト
jst_now = datetime.utcnow() + timedelta(hours=9)
start_date = (jst_now - timedelta(days=29)).date()

# 日付ごとの体重を格納する辞書
date_weights = {}

with open(SHARED_LOG, "r", encoding="utf-8") as f:
    for line in f:
        # 日付抽出（既存関数 extract_datetime を使える場合はそちらでOK）
        dt_match = re.search(r'\[(\d{4}/\d{2}/\d{2})', line)
        if dt_match:
            date = datetime.strptime(dt_match.group(1), "%Y/%m/%d").date()
            if date < start_date:
                continue
            weight_match = re.search(r'猫体重[:：]\s*(\d+(?:\.\d+)?)g', line)
            if weight_match:
                w = float(weight_match.group(1)) / 1000
                date_weights.setdefault(date, []).append(w)

# 確認用出力
for d in sorted(date_weights):
    avg_w = sum(date_weights[d])/len(date_weights[d])
    print(d, avg_w, date_weights[d])
