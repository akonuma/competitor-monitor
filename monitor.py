import requests
import hashlib
import json
import os
import difflib
from datetime import datetime, timezone

# ─── 環境変数から設定を読み込む ───
TARGET_URLS = json.loads(os.environ["TARGET_URLS"])
HASH_FILE   = "hashes.json"
CONTENT_DIR = "content_cache"  # ページ内容を保存するディレクトリ
TEAMS_WEBHOOK = os.environ["TEAMS_WEBHOOK"]


def load_hashes() -> dict:
    """リポジトリ上のハッシュファイルを読み込む"""
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE) as f:
            return json.load(f)
    return {}


def save_hashes(hashes: dict):
    """ハッシュファイルを書き込む"""
    with open(HASH_FILE, "w") as f:
        json.dump(hashes, f, indent=2)


def get_page_content(url: str) -> str | None:
    """ページの内容を取得"""
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SiteMonitorBot/1.0)"
        })
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[ERROR] {url} の取得に失敗: {e}")
        return None


def get_content_hash(content: str) -> str:
    """コンテンツのハッシュ値を計算"""
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def save_content(url: str, content: str):
    """ページ内容をファイルに保存"""
    os.makedirs(CONTENT_DIR, exist_ok=True)
    filename = hashlib.md5(url.encode('utf-8')).hexdigest() + ".txt"
    filepath = os.path.join(CONTENT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def load_content(url: str) -> str | None:
    """保存されたページ内容を読み込む"""
    filename = hashlib.md5(url.encode('utf-8')).hexdigest() + ".txt"
    filepath = os.path.join(CONTENT_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    return None


def get_diff_summary(old_content: str, new_content: str, max_lines: int = 10) -> str:
    """変更の差分サマリーを取得（最大行数制限付き）"""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    
    diff = list(difflib.unified_diff(
        old_lines, 
        new_lines, 
        lineterm='',
        n=0  # コンテキスト行を0にして変更部分のみ表示
    ))
    
    if not diff:
        return "変更なし"
    
    # ヘッダー行（@@で始まる行）を除外し、実際の変更行のみ抽出
    changes = []
    for line in diff[2:]:  # 最初の2行はファイル名なのでスキップ
        if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
            continue
        changes.append(line)
    
    # 最大行数まで切り詰め
    if len(changes) > max_lines:
        changes = changes[:max_lines]
        changes.append(f"... (他 {len(diff) - max_lines} 行の変更)")
    
    return "\n".join(changes) if changes else "詳細な変更内容を取得できませんでした"


def send_teams_alert(changed_urls: list[dict]):
    """変更されたURLについてTeams通知を送信（差分付き）"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 各URLの情報を sections として構築
    sections = [{
        "activityTitle": "変更検知サマリー",
        "activitySubtitle": f"検知時刻: {now}",
        "text": f"**{len(changed_urls)}件のサイトで変更を検知しました**"
    }]
    
    for item in changed_urls:
        url = item["url"]
        diff_summary = item.get("diff", "差分情報なし")
        
        sections.append({
            "activityTitle": f"📝 {url}",
            "text": f"```\n{diff_summary[:500]}\n```"  # 最大500文字
        })

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"競合サイト更新検知 ({len(changed_urls)}件)",
        "themeColor": "0078D4",
        "title": f"🔔 競合サイト更新検知 ({len(changed_urls)}件)",
        "sections": sections
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
        current_content = get_page_content(url)
        if current_content is None:
            continue

        current_hash = get_content_hash(current_content)
        prev_hash = hashes.get(url)

        if prev_hash is None:
            # 初回登録
            print(f"[NEW]     {url}")
            hashes[url] = current_hash
            save_content(url, current_content)
        elif current_hash != prev_hash:
            # 変更検知
            print(f"[CHANGED] {url}")
            
            # 前回のコンテンツを取得して差分を計算
            old_content = load_content(url)
            diff_summary = "前回のコンテンツが見つかりません"
            
            if old_content:
                diff_summary = get_diff_summary(old_content, current_content, max_lines=15)
            
            changed.append({
                "url": url,
                "diff": diff_summary
            })
            
            # 新しいハッシュとコンテンツを保存
            hashes[url] = current_hash
            save_content(url, current_content)
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
