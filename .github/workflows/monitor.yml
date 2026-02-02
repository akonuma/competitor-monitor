import requests
import hashlib
import json
import os
from datetime import datetime, timezone

# ─── 環境変数から設定を読み込む ───
TARGET_URLS = json.loads(os.environ["TARGET_URLS"])
HASH_FILE   = "hashes.json"
TEAMS_WEBHOOK = os.environ["TEAMS_WEBHOOK"]  # Teams Webhook URL


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


def send_teams_alert(changed_urls: list[str]):
    """変更されたURLについてTeams通知を送信"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Teams Adaptive Card 形式
    facts = [{"name": f"URL {i+1}", "value": url} for i, url in enumerate(changed_urls)]

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"競合サイト更新検知 ({len(changed_urls)}件)",
        "themeColor": "0078D4",
        "title": f"🔔 競合サイト更新検知 ({len(changed_urls)}件)",
        "sections": [
            {
                "activityTitle": "変更されたサイト",
                "activitySubtitle": f"検知時刻: {now}",
                "facts": facts
            }
        ]
    }

    try:
        resp = requests.post(TEAMS_WEBHOOK, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"[OK] Teams通知送信完了")
    except Exception as e:
        print(f"[ERROR] Teams通知送信失敗: {e}")


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

    # ハッシュファイルを更新
    save_hashes(hashes)

    # 変更があればTeams通知
    if changed:
        send_teams_alert(changed)
    else:
        print("[INFO] 変更なし")

    print("[END] チェック完了")


if __name__ == "__main__":
    main()
