import requests
import hashlib
import json
import os
import difflib
import re
from datetime import datetime, timezone

# ─── 環境変数から設定を読み込む ───
TARGET_URLS = json.loads(os.environ["TARGET_URLS"])
HASH_FILE   = "hashes.json"import requests
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
    # 画像タグから URL と alt を抽出して保存
    images = []
    for match in re.finditer(r'<img[^>]*>', html, re.IGNORECASE):
        img_tag = match.group(0)
        # src 属性を抽出
        src_match = re.search(r'src=["\']([^"\']+)["\']', img_tag, re.IGNORECASE)
        # alt 属性を抽出
        alt_match = re.search(r'alt=["\']([^"\']*)["\']', img_tag, re.IGNORECASE)
        
        if src_match:
            src = src_match.group(1)
            alt = alt_match.group(1) if alt_match else ""
            images.append(f"[IMAGE: {src}]" + (f" (alt: {alt})" if alt else ""))
    
    # スクリプトとスタイルを除去
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # コメントを除去
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    # HTML タグを除去
    text = re.sub(r'<[^>]+>', '\n', html)  # タグを改行に置換
    # HTML エンティティをデコード
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&apos;', "'")
    
    # 空白・改行を完全に正規化
    # 1. 連続する空白を1つにまとめる
    text = re.sub(r'[ \t]+', ' ', text)
    # 2. 行ごとに分割してトリム
    lines = [line.strip() for line in text.split('\n')]
    # 3. 空行を除去
    lines = [line for line in lines if line]
    # 4. 意味のある単位（文や段落）で改行
    # 句読点の後に適切な改行を入れる
    normalized_lines = []
    for line in lines:
        # 長すぎる行は句読点で分割
        if len(line) > 100:
            # 。や！？で分割
            sentences = re.split(r'([。！？\.!?])', line)
            current = ""
            for i in range(0, len(sentences), 2):
                sentence = sentences[i]
                punct = sentences[i+1] if i+1 < len(sentences) else ""
                current += sentence + punct
                if len(current) > 80 or punct in ['。', '！', '？', '.', '!', '?']:
                    if current.strip():
                        normalized_lines.append(current.strip())
                    current = ""
            if current.strip():
                normalized_lines.append(current.strip())
        else:
            normalized_lines.append(line)
    
    # テキストと画像情報を結合
    if images:
        normalized_lines.append("")
        normalized_lines.append("--- 画像一覧 ---")
        normalized_lines.extend(images)
    
    return '\n'.join(normalized_lines)


def get_text_content_hash(html: str) -> str:
    """テキストコンテンツのハッシュ値を計算（HTMLタグを除去後）"""
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
    """変更の差分サマリーを取得（変更箇所のみ表示）"""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    
    # 完全一致チェック
    if old_lines == new_lines:
        return "変更なし"
    
    diff = list(difflib.unified_diff(
        old_lines, 
        new_lines, 
        lineterm='',
        n=0  # コンテキスト行なし（変更箇所のみ）
    ))
    
    if not diff or len(diff) <= 2:
        return "変更なし"
    
    # 実際の変更行のみ抽出
    added = []
    removed = []
    
    for line in diff[2:]:  # 最初の2行（ファイル名）はスキップ
        if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
            continue
        elif line.startswith('+'):
            added.append(line[1:].strip())
        elif line.startswith('-'):
            removed.append(line[1:].strip())
    
    # 変更がない場合
    if not added and not removed:
        return "変更なし"
    
    # 分かりやすい形式で出力
    result = []
    
    if removed:
        result.append("【削除された内容】")
        for i, line in enumerate(removed[:max_changes], 1):
            if line:  # 空行は除外
                result.append(f"  - {line}")
        if len(removed) > max_changes:
            result.append(f"  ... 他 {len(removed) - max_changes} 行")
    
    if added:
        if removed:
            result.append("")  # 空行で区切る
        result.append("【追加された内容】")
        for i, line in enumerate(added[:max_changes], 1):
            if line:  # 空行は除外
                result.append(f"  + {line}")
        if len(added) > max_changes:
            result.append(f"  ... 他 {len(added) - max_changes} 行")
    
    return '\n'.join(result) if result else "変更なし"


def send_teams_alert(changed_urls: list[dict]):
    """変更されたURLについてTeams通知を送信（テキスト差分のみ）"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    sections = [{
        "activityTitle": "変更検知サマリー",
        "activitySubtitle": f"検知時刻: {now}",
        "text": f"**{len(changed_urls)}件のサイトで実質的な内容変更を検知しました**"
    }]
    
    for item in changed_urls:
        url = item["url"]
        text_diff = item.get("text_diff", "差分情報なし")
        
        sections.append({
            "activityTitle": f"📝 {url}",
            "activitySubtitle": "**変更内容（テキスト差分）**",
            "text": f"```\n{text_diff[:1500]}\n```"
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
        current_html = get_page_content(url)
        if current_html is None:
            continue

        # テキストコンテンツのハッシュを計算（HTMLタグ除去後）
        current_hash = get_text_content_hash(current_html)
        prev_hash = hashes.get(url)

        if prev_hash is None:
            # 初回登録
            print(f"[NEW]     {url}")
            hashes[url] = current_hash
            save_content(url, current_html)
        elif current_hash != prev_hash:
            # テキストコンテンツが変更された
            print(f"[CHANGED] {url}")
            
            old_html = load_content(url)
            text_diff = "前回のコンテンツが見つかりません"
            
            if old_html:
                # テキストのみ抽出して差分を作成
                old_text = strip_html_tags(old_html)
                new_text = strip_html_tags(current_html)
                text_diff = get_diff_summary(old_text, new_text, max_changes=20)
            
            changed.append({
                "url": url,
                "text_diff": text_diff
            })
            
            hashes[url] = current_hash
            save_content(url, current_html)
        else:
            print(f"[OK]      {url} (テキストコンテンツ変更なし)")

    save_hashes(hashes)

    if changed:
        send_teams_alert(changed)
    else:
        print("[INFO] 実質的な変更なし")

    print("[END] チェック完了")


if __name__ == "__main__":
    main()
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
    # 画像タグから URL と alt を抽出して保存
    images = []
    for match in re.finditer(r'<img[^>]*>', html, re.IGNORECASE):
        img_tag = match.group(0)
        # src 属性を抽出
        src_match = re.search(r'src=["\']([^"\']+)["\']', img_tag, re.IGNORECASE)
        # alt 属性を抽出
        alt_match = re.search(r'alt=["\']([^"\']*)["\']', img_tag, re.IGNORECASE)
        
        if src_match:
            src = src_match.group(1)
            alt = alt_match.group(1) if alt_match else ""
            images.append(f"[IMAGE: {src}]" + (f" (alt: {alt})" if alt else ""))
    
    # スクリプトとスタイルを除去
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # コメントを除去
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    # HTML タグを除去
    text = re.sub(r'<[^>]+>', '', html)
    # HTML エンティティをデコード
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    # 連続する空白を1つにまとめる
    text = re.sub(r'\s+', ' ', text)
    # 各行をトリム
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # テキストと画像情報を結合
    if images:
        lines.append("\n--- 画像一覧 ---")
        lines.extend(images)
    
    return '\n'.join(lines)


def get_text_content_hash(html: str) -> str:
    """テキストコンテンツのハッシュ値を計算（HTMLタグを除去後）"""
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


def get_diff_summary(old_content: str, new_content: str, max_lines: int = 20) -> str:
    """変更の差分サマリーを取得"""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    
    diff = list(difflib.unified_diff(
        old_lines, 
        new_lines, 
        lineterm='',
        n=1  # 前後1行のコンテキストを表示
    ))
    
    if not diff:
        return "変更なし"
    
    changes = []
    for line in diff[2:]:  # 最初の2行（ファイル名）はスキップ
        if line.startswith('---') or line.startswith('+++'):
            continue
        changes.append(line)
    
    if len(changes) > max_lines:
        changes = changes[:max_lines]
        changes.append(f"... (他 {len(changes) - max_lines} 行以上)")
    
    return '\n'.join(changes) if changes else "差分なし"


def send_teams_alert(changed_urls: list[dict]):
    """変更されたURLについてTeams通知を送信（テキスト差分のみ）"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    sections = [{
        "activityTitle": "変更検知サマリー",
        "activitySubtitle": f"検知時刻: {now}",
        "text": f"**{len(changed_urls)}件のサイトで実質的な内容変更を検知しました**"
    }]
    
    for item in changed_urls:
        url = item["url"]
        text_diff = item.get("text_diff", "差分情報なし")
        
        sections.append({
            "activityTitle": f"📝 {url}",
            "activitySubtitle": "**変更内容（テキスト差分）**",
            "text": f"```\n{text_diff[:1500]}\n```"
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
        current_html = get_page_content(url)
        if current_html is None:
            continue

        # テキストコンテンツのハッシュを計算（HTMLタグ除去後）
        current_hash = get_text_content_hash(current_html)
        prev_hash = hashes.get(url)

        if prev_hash is None:
            # 初回登録
            print(f"[NEW]     {url}")
            hashes[url] = current_hash
            save_content(url, current_html)
        elif current_hash != prev_hash:
            # テキストコンテンツが変更された
            print(f"[CHANGED] {url}")
            
            old_html = load_content(url)
            text_diff = "前回のコンテンツが見つかりません"
            
            if old_html:
                # テキストのみ抽出して差分を作成
                old_text = strip_html_tags(old_html)
                new_text = strip_html_tags(current_html)
                text_diff = get_diff_summary(old_text, new_text, max_lines=30)
            
            changed.append({
                "url": url,
                "text_diff": text_diff
            })
            
            hashes[url] = current_hash
            save_content(url, current_html)
        else:
            print(f"[OK]      {url} (テキストコンテンツ変更なし)")

    save_hashes(hashes)

    if changed:
        send_teams_alert(changed)
    else:
        print("[INFO] 実質的な変更なし")

    print("[END] チェック完了")


if __name__ == "__main__":
    main()
