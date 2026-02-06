import requests
import hashlib
import json
import os
import difflib
import re
from datetime import datetime, timezone

# ─── 環境変数から設定を読み込む ───
# TARGET_URLS は ['https://...'] の形式のJSON文字列を想定
TARGET_URLS = json.loads(os.environ.get("TARGET_URLS", "[]"))
HASH_FILE    = "hashes.json"
CONTENT_DIR = "content_cache"
TEAMS_WEBHOOK = os.environ.get("TEAMS_WEBHOOK", "")


def load_hashes() -> dict:
    """リポジトリ上のハッシュファイルを読み込む"""
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE) as f:
            try:
                return json.load(f)
            except:
                return {}
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


def strip_html_tags(html: str) -> str:
    """HTML タグを除去してテキストのみ抽出（画像URL・alt属性も含む）"""
    images = []
    for match in re.finditer(r'<img[^>]*>', html, re.IGNORECASE):
        img_tag = match.group(0)
        src_match = re.search(r'src=["\']([^"\']+)["\']', img_tag, re.IGNORECASE)
        alt_match = re.search(r'alt=["\']([^"\']*)["\']', img_tag, re.IGNORECASE)
        
        if src_match:
            src = src_match.group(1)
            alt = alt_match.group(1) if alt_match else ""
            # 特定の動的パラメータ（タイムスタンプ等）が含まれる場合は無視する等の処理が必要な場合もあるが、一旦そのまま
            images.append(f"[IMAGE: {src}]" + (f" (alt: {alt})" if alt else ""))
    
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    
    text = re.sub(r'<[^>]+>', '\n', html)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&apos;', "'")
    
    text = re.sub(r'[ \t]+', ' ', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    if images:
        lines.append("")
        lines.append("--- 画像一覧 ---")
        lines.extend(images)
    
    return '\n'.join(lines)


def get_text_content_hash(html: str) -> str:
    """テキストコンテンツのハッシュ値を計算"""
    text = strip_html_tags(html)
    return hashlib.md5(text.encode('utf-8')).hexdigest()


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


def get_diff_summary(old_content: str, new_content: str, max_changes: int = 15) -> str:
    """変更の差分サマリーを取得。本当に変更がある場合のみ文字列を返す"""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    
    if old_lines == new_lines:
        return "変更なし"
    
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=0))
    
    added = []
    removed = []
    for line in diff[2:]:
        if line.startswith('+') and not line.startswith('+++'):
            added.append(line[1:].strip())
        elif line.startswith('-') and not line.startswith('---'):
            removed.append(line[1:].strip())
    
    if not added and not removed:
        return "変更なし"
    
    result = []
    if removed:
        result.append("【削除された内容】")
        for line in removed[:max_changes]:
            if line: result.append(f"  - {line}")
        if len(removed) > max_changes: result.append(f"  ... 他 {len(removed) - max_changes} 行")
    
    if added:
        if removed: result.append("")
        result.append("【追加された内容】")
        for line in added[:max_changes]:
            if line: result.append(f"  + {line}")
        if len(added) > max_changes: result.append(f"  ... 他 {len(added) - max_changes} 行")
    
    return '\n'.join(result)


def send_teams_alert(changed_urls: list[dict]):
    """Teams通知を送信"""
    if not TEAMS_WEBHOOK:
        print("[ERROR] TEAMS_WEBHOOK が設定されていません")
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    sections = [{
        "activityTitle": "変更検知サマリー",
        "activitySubtitle": f"検知時刻: {now}",
        "text": f"**{len(changed_urls)}件のサイトで実質的な内容変更を検知しました**"
    }]
    
    for item in changed_urls:
        sections.append({
            "activityTitle": f"📝 {item['url']}",
            "activitySubtitle": "**変更内容（テキスト差分）**",
            "text": f"
