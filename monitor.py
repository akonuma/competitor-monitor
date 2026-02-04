import requests
import hashlib
import json
import os
import difflib
import re
from datetime import datetime, timezone

# ─── 環境変数から設定を読み込む ───
TARGET_URLS = json.loads(os.environ["TARGET_URLS"])
HASH_FILE   = "hashes.json"
CONTENT_DIR = "content_cache"
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


def normalize_content(content: str) -> str:
    """動的に変わる要素を正規化して無視する"""
    
    # 1. タイムスタンプ系の属性を削除
    patterns = [
        # WOVN のキャッシュタイム
        r'data-wovnio-cache-time="[^"]*"',
        # 一般的なタイムスタンプ
        r'timestamp="[^"]*"',
        r'data-timestamp="[^"]*"',
        # 日時を含むメタタグ
        r'content="[0-9]{12,14}\+[0-9]{4}"',
        # CSRFトークンなど
        r'csrf[-_]token[^>]*value="[^"]*"',
        r'data-csrf="[^"]*"',
        # セッションID
        r'session[-_]id="[^"]*"',
        # ランダムなID
        r'id="[a-f0-9]{32,}"',
        # Google Analytics など
        r'_ga=[^&\s"]*',
        r'gtm\.start=[^&\s"]*',
        # A/Bテスト・実験ID
        r'data-experiment[^>]*="[^"]*"',
        r'name="edge-experiment-treatments"\s+content="[^"]*"',
        r'data-testid="[^"]*"',
    ]
    
    normalized = content
    for pattern in patterns:
        normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
    
    # 2. 連続する空白を1つにまとめる（正規化のため）
    normalized = re.sub(r'\s+', ' ', normalized)
    
    return normalized


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


def strip_html_tags(html: str) -> str:
    """HTML タグを除去してテキストのみ抽出"""
    # スクリプトとスタイルを除去
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # HTML タグを除去
    text = re.sub(r'<[^>]+>', '', html)
    # 連続する空白を1つにまとめる
    text = re.sub(r'\s+', ' ', text)
    # 各行をトリム
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return '\n'.join(lines)


def get_content_hash(content: str) -> str:
    """コンテンツのハッシュ値を計算（正規化後）"""
    normalized = normalize_content(content)
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()


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
    """変更の差分サマリーを取得"""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    
    diff = list(difflib.unified_diff(
        old_lines, 
        new_lines, 
        lineterm='',
        n=0
    ))
    
    if not diff:
        return "変更なし"
    
    changes = []
    for line in diff[2:]:
        if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
            continue
        changes.append(line)
    
    if len(changes) > max_lines:
        changes = changes[:max_lines]
        changes.append(f"... (他 {len(diff) - max_lines} 行)")
    
    return '\n'.join(changes) if changes else "差分なし"


def send_teams_alert(changed_urls: list[dict]):
    """変更されたURLについてTeams通知を送信（テキスト差分 + HTML差分）"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    sections = [{
        "activityTitle": "変更検知サマリー",
        "activitySubtitle": f"検知時刻: {now}",
        "text": f"**{len(changed_urls)}件のサイトで変更を検知しました**"
    }]
    
    for item in changed_urls:
        url = item["url"]
        text_diff = item.get("text_diff", "差分情報なし")
        html_diff = item.get("html_diff", "差分情報なし")
        
        # テキスト差分（読みやすい）
        sections.append({
            "activityTitle": f"📝 {url}",
            "activitySubtitle": "**テキスト差分（読みやすい表示）**",
            "text": f"```\n{text_diff[:800]}\n```"
        })
        
        # HTML差分（詳細確認用）
        sections.append({
            "activitySubtitle": "**HTML差分（詳細確認用）**",
            "text": f"```html\n{html_diff[:500]}\n```"
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
            
            old_content = load_content(url)
            text_diff = "前回のコンテンツが見つかりません"
            html_diff = "前回のコンテンツが見つかりません"
            
            if old_content:
                # 正規化して比較
                old_normalized = normalize_content(old_content)
                new_normalized = normalize_content(current_content)
                
                # テキスト差分を作成
                old_text = strip_html_tags(old_normalized)
                new_text = strip_html_tags(new_normalized)
                text_diff = get_diff_summary(old_text, new_text, max_lines=20)
                
                # HTML差分を作成
                html_diff = get_diff_summary(old_normalized, new_normalized, max_lines=10)
            
            changed.append({
                "url": url,
                "text_diff": text_diff,
                "html_diff": html_diff
            })
            
            hashes[url] = current_hash
            save_content(url, current_content)
        else:
            print(f"[OK]      {url}")

    save_hashes(hashes)

    if changed:
        send_teams_alert(changed)
    else:
        print("[INFO] 変更なし")

    print("[END] チェック完了")


if __name__ == "__main__":
    main()
