# -*- coding: utf-8 -*-
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.models import ImageSendMessage
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pandas as pd
import os
# ユーザーごとの会話履歴を保存
from collections import defaultdict

session_history = defaultdict(list)


ngrok_url = " https://2ec1d662bd50.ngrok-free.app"


# アクセストークンとシークレット
LINE_CHANNEL_ACCESS_TOKEN = '38nsajkWI8nFC/rCJA9zQnZzb3Z/7N/5XpDmlRHzMRUvTLWvBuug8bFl8j9oF4wo7fzLX+Ch2mbhHg42VfvGv12uV8Vt/TgpmCMY4Fpyxkgaz574+HaowbPI0H+jq5uzVzQBBZNU/hPv7Fhr6/zIgAdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = 'ad72b145d77f064372450c467de2d99b'

app = Flask(__name__, static_url_path='/static')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

import gspread
from oauth2client.service_account import ServiceAccountCredentials

def save_to_sheet(user_id, score, message):
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    credentials_path = '/etc/secrets/GOOGLE_CREDENTIALS_JSON'
    
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        'your-credentials.json', scope)
    client = gspread.authorize(creds)
    sheet = client.open("CounselingLog").sheet1
    sheet.append_row([user_id, score, message])


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print(f"[署名検証エラー] {e}")  # エラーの中身が見える
        abort(400)

    return 'OK'

from openai import OpenAI

client = OpenAI(
    api_key="TUwPNq4V8XuVHz83QnQWznMzSaImlcyQIBfzFCQ7y6PRkj91NVQcbtApyg4iir3EysKyNn-ZFPMRW2UM3nAhErA",

    base_url="https://api.openai.iniad.org/api/v1",
)

#スコアの保存
import csv
from datetime import datetime

def save_score(user_id, score):
    with open("scores.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), user_id, score])


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text
    
    # ここで感情スコアを計算（例：score = analyze_emotion(user_message)）
    score = analyze_emotion(user_message)  # 自分で定義した感情分析関数

    # スプレッドシートに保存
    save_to_sheet(user_id, score, user_message)

    # 応答
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="メッセージを受け取りました。ありがとう！")
    )


    # まずはグラフ要求かチェック
    if any(keyword in user_message.lower() for keyword in ["グラフ", "グラフくれ", "グラフみたい", "気分の推移", "推移"]):
        filename = generate_graph(user_id)
        if filename:
            image_url = f"{ngrok_url}/static/{filename}"
            print("[送信する画像URL]", image_url)
            image_message = ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            )
            line_bot_api.reply_message(event.reply_token, image_message)
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="まだ十分なデータがありません。もう少しやりとりしてからグラフが見れます。")
            )
        return

    # 会話履歴にユーザーの発言を追加
    session_history[user_id].append({"role": "user", "content": user_message})

    # 会話履歴をAPIに送信
    try:
        messages = [{"role": "system", "content": "あなたは公認心理師です。..."}] + session_history[user_id]

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7,
        )

        reply_text = response.choices[0].message.content

        # GPTの応答も履歴に追加
        session_history[user_id].append({"role": "assistant", "content": reply_text})

        # スコア抽出して保存（任意）
        import re
        score_match = re.search(r'\d+', reply_text)
        if score_match:
            score = int(score_match.group())
            save_score(user_id, score)

    except Exception as e:
        reply_text = f"[GPTエラー]: {str(e)}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

   
#グラフの作成

def generate_graph(user_id):
    df = pd.read_csv("scores.csv", header=None, names=["time", "user_id", "score"])
    df_user = df[df["user_id"] == user_id]

    font_path = "C:/Windows/Fonts/meiryo.ttc"  # ← Windowsのメイリオ
    jp_font = fm.FontProperties(fname=font_path)

    if len(df_user) < 2:
        return None 
    
    plt.figure(figsize=(6,4),dpi=100)
    plt.plot(pd.to_datetime(df_user["time"]), df_user["score"], marker="o")
    plt.title("気分スコアの推移", fontproperties=jp_font)
    plt.xlabel("時間", fontproperties=jp_font)
    plt.ylabel("スコア", fontproperties=jp_font)
    plt.ylim(0, 100)
    plt.grid(True)

    os.makedirs("static", exist_ok=True)  # staticフォルダがなければ作成
    file_path = f"static/graph_{user_id}.png"
    plt.savefig(file_path)
    plt.close()
    return os.path.basename(file_path)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)





