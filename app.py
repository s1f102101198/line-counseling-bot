# -*- coding: utf-8 -*-
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pandas as pd
import os
from collections import defaultdict
import csv
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

# 会話履歴保持
session_history = defaultdict(list)

# Flaskアプリ作成
app = Flask(__name__, static_url_path='/static')

# LINE設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'your_token')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', 'your_secret')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# OpenAIクライアント
from openai import OpenAI
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "your_key"),
    base_url="https://api.openai.iniad.org/api/v1"
)

# グラフ表示用URL（ngrok用・Render用に環境変数で切替）
BASE_URL = os.getenv("BASE_URL", "https://your-render-app.onrender.com")

# Google Sheets保存
import tempfile
import json

def save_to_sheet(user_id, score, message):
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']

    # Render の環境変数には JSON 全文を保存している前提
    json_str = os.getenv('GOOGLE_CREDENTIALS_JSON')

    if not json_str:
        raise ValueError("GOOGLE_CREDENTIALS_JSON 環境変数が設定されていません")

    # 一時ファイルとして保存
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as temp_file:
        temp_file.write(json_str)
        temp_file_path = temp_file.name

    creds = ServiceAccountCredentials.from_json_keyfile_name(temp_file_path, scope)
    client = gspread.authorize(creds)
    sheet = client.open("CounselingLog").sheet1
    sheet.append_row([user_id, score, message])

# スコアCSV保存
def save_score(user_id, score):
    with open("scores.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), user_id, score])

# グラフ作成
def generate_graph(user_id):
    df = pd.read_csv("scores.csv", header=None, names=["time", "user_id", "score"])
    df_user = df[df["user_id"] == user_id]

    if len(df_user) < 2:
        return None

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if os.name == "nt":  # Windows
        font_path = "C:/Windows/Fonts/meiryo.ttc"
    jp_font = fm.FontProperties(fname=font_path)

    plt.figure(figsize=(6, 4), dpi=100)
    plt.plot(pd.to_datetime(df_user["time"]), df_user["score"], marker="o")
    plt.title("気分スコアの推移", fontproperties=jp_font)
    plt.xlabel("時間", fontproperties=jp_font)
    plt.ylabel("スコア", fontproperties=jp_font)
    plt.ylim(0, 100)
    plt.grid(True)

    os.makedirs("static", exist_ok=True)
    file_path = f"static/graph_{user_id}.png"
    plt.savefig(file_path)
    plt.close()
    return os.path.basename(file_path)

# LINE Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# メッセージイベント処理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    # 返信を先に返す（reply_token失効対策）
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="メッセージを受け取りました！内容を処理中です...")
    )

    # 感情スコア解析（例：ランダム）
    score = analyze_emotion(user_message)
    save_to_sheet(user_id, score, user_message)
    save_score(user_id, score)

    # グラフ希望か？
    if any(k in user_message for k in ["グラフ", "推移", "見せて", "気分"]):
        filename = generate_graph(user_id)
        if filename:
            image_url = f"{BASE_URL}/static/{filename}"
            line_bot_api.push_message(user_id, ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            ))
        else:
            line_bot_api.push_message(user_id, TextSendMessage(
                text="まだ十分なデータがありません。"
            ))
        return

    # 履歴追加
    session_history[user_id].append({"role": "user", "content": user_message})

    try:
        messages = [{"role": "system", "content": "あなたは公認心理師です。相手を傷つけないように注意してください。"}] + session_history[user_id]

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply_text = response.choices[0].message.content
        session_history[user_id].append({"role": "assistant", "content": reply_text})

        score_match = re.search(r'\d+', reply_text)
        if score_match:
            score = int(score_match.group())
            save_score(user_id, score)

        line_bot_api.push_message(user_id, TextSendMessage(text=reply_text))

    except Exception as e:
        line_bot_api.push_message(user_id, TextSendMessage(text=f"[エラー] {str(e)}"))

# ダミー感情スコア関数
def analyze_emotion(text):
    return 50  # あとでAIや感情APIと連携可能

# アプリ起動
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
