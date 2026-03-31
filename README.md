# ハチのトイレ監視 & AI日報システム 技術詳細仕様書

## 📁 1. ファイル一覧と役割 (Project Structure)
本プロジェクトを構成する全ファイルのリストです。

/volume1/docker/ai-analysis/
├── docker-compose.yml   # 全体の司令塔。analyzerとresponderを管理
├── .env                 # APIキー保管庫（Gemini API / LINE API）
├── summary.txt          # データベース。AIの解析結果が蓄積される日記
├── README.md            # 本書
│
├── [解析系：analyzerコンテナ]
│   ├── Dockerfile       # 解析用環境（watchdog, google-genai等）
│   ├── analyze.py       # 常時監視。新しい画像が保存されたら即座にAI解析
│   ├── initial_batch.py # 全構築。過去の全画像をファイル名時刻で再解析
│   └── test_one.py      # テスト。最新1枚で時刻とAI判定を検証
│
└── [応答系：responderコンテナ]
    ├── Dockerfile       # 応答用環境（Flask, line-bot-sdk等）
    └── responder.py     # LINE応答。Webhookを受けてsummary.txtを返信

---

## 🚀 2. 実行コマンド一覧 (Operations)

### ■ システム全体の操作
- 起動・更新: `docker-compose up -d --build`
- 停止: `docker-compose down`
- リアルタイムログ確認: `docker-compose logs -f`

### ■ プログラムごとの個別実行
1. 日記を最初から作り直す（時刻ズレ修正・プロンプト変更時）
   命令: `docker-compose exec analyzer python3 initial_batch.py`

2. 時刻取得とAI判定をテストする
   命令: `docker-compose exec analyzer python3 test_one.py`

---

## 🛠️ 3. 内部ロジックとLINE連携の詳細

### A. 時刻抽出ロジック (Regex Extraction)
カメラが生成するファイル名（例: Living Room_00_20260117105024.jpg）から、正規表現を用いて末尾の14桁を抽出。これにより、Dockerコンテナのシステム時刻がズレていても、画像が撮影された「真の日本時間」を日記に記録します。

### B. LINE Messaging API 連携
- responder.py が Flask サーバーとして 8000番ポートで待機。
- LINE Developers の Webhook URL に設定されたアドレスからリクエストを受信。
- 「最新」「まとめ」といったキーワードを summary.txt 内から検索し、ユーザーにプッシュまたはリプライで返信します。

## 📅 4. 将来の拡張（Alexa / E1 Pro 増設）
- 玄関や子供部屋にカメラを増設した際は、このディレクトリ構成を元に新しい監視パス(WATCH_DIR)を設定。
- Alexa Developer Console と連携させ、特定のAI解析結果（例：人物検知）をトリガーに Alexa デバイスから音声通知を出す拡張を想定しています。

---
最終更新: 2026-01-17 / 作成者: ハチの飼い主 & Gemini
