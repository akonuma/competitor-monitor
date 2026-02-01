import requests
import hashlib
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

# ─── 環境変数から設定を読み込む ───
TARGET_URLS = json.loads(os.environ["TARGET_URLS"])          # '["url1","url2"]'
HASH_FILE   = "hashes.json"                                  # リポジトリ上に保存するハッシュファイル

SMTP_SERVER   = os.environ.get("SMTP_SERVER",   "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ["SMTP_USER"]                      # Gmail アドレス
SMTP_PASS     = os.environ["SMTP_PASS"]                      # Gmail アプリパスワード
ALERT_TO      = os.environ["ALERT_TO"]                       # 通知先メールアドレス


def load_hashes() -> dict:
    """リポジトリ上のハッシュファイルを読み込む"""
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE) as f:
            return json.load(f)
    return {}


def save_hashes(hashes: dict):
    """ハッシュファイルを書き込む（GitHub Actions で git push する）"""
    with open(HASH_FILE, "w") as f:
        json.dump(hashes, f, indent=2)


def get_page_hash(url: str) -> str | None:
    """ページの MD5 ハッシュを取得"""
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SiteMonitorBot/1.0)"
        })
        resp.raise_for_status()
        return hashlib.md5(resp.content).hexdigest()
    except Exception as e:
        print(f"[ERROR] {url} の取得に失敗: {e}")
        return None


def send_alert(changed_urls: list[str]):
    """変更されたURLについてメールアラートを送信"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    subject = f"🔔 競合サイト更新検知 ({len(changed_urls)}件) - {now}"

    body_lines = [
        f"検知時刻: {now}",
        f"変更件数: {len(changed_urls)} サイト",
        "",
        "─── 変更されたURL ───",
    ]
    for url in changed_urls:
        body_lines.append(f"  ✅ {url}")

    body = "\n".join(body_lines)

    msg = MIMEMultipart()
    msg["From"]    = SMTP_USER
    msg["To"]      = ALERT_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"[OK] アラートメール送信完了 → {ALERT_TO}")
    except Exception as e:
        print(f"[ERROR] メール送信に失敗: {e}")


def main():
    print(f"[START] {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} チェック開始")

    hashes = load_hashes()
    changed = []

    for url in TARGET_URLS:
        current_hash = get_page_hash(url)
        if current_hash is None:
            continue

        prev_hash = hashes.get(url)

        if prev_hash is None:
            # 初回登録
            print(f"[NEW]     {url}")
            hashes[url] = current_hash
        elif current_hash != prev_hash:
            # 変更検知
            print(f"[CHANGED] {url}")
            hashes[url] = current_hash
            changed.append(url)
        else:
            print(f"[OK]      {url}")

    # ハッシュファイルを更新（Actions で git push される）
    save_hashes(hashes)

    # 変更があればアラート送信
    if changed:
        send_alert(changed)
    else:
        print("[INFO] 変更なし")

    print("[END] チェック完了")


if __name__ == "__main__":
    main()
