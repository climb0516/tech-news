#!/usr/bin/env python3
"""Daily news scraper — fetches from global + Chinese tech media and inserts into Supabase."""
import html, json, re, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

SUPABASE_URL = "https://sqrzrvstlvxqxdxvhlxz.supabase.co"
ANON_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNxcnpydnN0bHZ4cXhkeHZobHh6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwMTUzMjAsImV4cCI6MjA5NjU5MTMyMH0.C6Gz61TB3GhLnbDWywogGZDcqTu1G2ta9-Dyo60Yiho"
TODAY        = datetime.now(timezone.utc).strftime("%Y-%m-%d")
UA           = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# ── Category heuristics ───────────────────────────────────────────────────────

def categorize(title, summary=""):
    t = (title + " " + summary).lower()
    if any(k in t for k in ["llm","large language","gpt","claude","gemini","mistral","llama","deepseek","qwen",
                              "arxiv","neural","transformer","benchmark","foundation model","multimodal",
                              "diffusion","reasoning model","o1","o3","ai research",
                              "大模型","大语言模型","多模态","推理模型","基座模型","通义","文心","豆包","混元",
                              "kimi","智谱","月之暗面","论文","算力","训练","具身智能"]):
        return "A"
    if any(k in t for k in ["chatgpt","copilot","cursor","openai","anthropic","ai tool","ai product",
                              "plugin","ai assistant","agent","launch","new feature",
                              "智能体","ai 助手","ai助手","ai 应用","ai应用","ai 产品","人工智能","aigc"]):
        return "B"
    if any(k in t for k in ["open source","open-source","github","hugging face","ollama",
                              "npm release","pypi","new library","repo",
                              "开源","开发者社区","代码仓库"]):
        return "C"
    if any(k in t for k in ["react","vue","svelte","swift","kotlin","android","ios","javascript",
                              "typescript","rust","golang","python","frontend","backend","docker",
                              "kubernetes","devops","next.js","database","postgres","redis","web dev",
                              "前端","后端","数据库","编程","程序员","鸿蒙","harmonyos","云原生","架构","编译器"]):
        return "D"
    return "E"

# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_url(url, timeout=10):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()

def fetch_json(url, timeout=10):
    return json.loads(fetch_url(url, timeout))

def clean_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()

def truncate(text, n=500):
    text = re.sub(r"\s+", " ", clean_html(text)).strip()
    return (text[:n] + "…") if len(text) > n else text

def make_item(category, title, source, summary, url, image_url=None):
    # 摘要与标题相同等于没有摘要，置空（前端不再重复显示）
    if (summary or "").strip() == (title or "").strip():
        summary = ""
    return {
        "category":  category,
        "title":     title,
        "source":    source,
        "summary":   summary,
        "url":       url or "",
        "date":      TODAY,
        "type":      "scraped",
        "image_url": image_url,
    }

# ── Sources ───────────────────────────────────────────────────────────────────

def fetch_hn(limit=15):
    print("→ Hacker News")
    items = []
    try:
        # Algolia HN API — 公开无认证，Actions 环境稳定
        data = fetch_json(f"https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}")
        for hit in data.get("hits", []):
            title = hit.get("title", "")
            url   = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID','')}"
            # 表里没有分数 / 评论数列，拼成摘要（前端按「▲ N 分 · M 条评论」解析）
            stats = f"▲ {hit.get('points') or 0} 分 · {hit.get('num_comments') or 0} 条评论"
            if title:
                items.append(make_item(categorize(title), title, "Hacker News", stats, url))
    except Exception as e:
        print(f"  error: {e}")
    print(f"  {len(items)} items")
    return items


def fetch_devto(limit=12):
    print("→ Dev.to")
    items = []
    try:
        articles = fetch_json(f"https://dev.to/api/articles?per_page={limit}&top=7")
        for a in articles:
            title   = a.get("title", "")
            summary = truncate(a.get("description") or title)
            image   = a.get("cover_image") or a.get("social_image")
            items.append(make_item(categorize(title, summary), title, "Dev.to", summary, a.get("url",""), image))
    except Exception as e:
        print(f"  error: {e}")
    print(f"  {len(items)} items")
    return items


def fetch_github_trending(limit=10):
    print("→ GitHub Trending")
    items = []
    try:
        html  = fetch_url("https://github.com/trending?since=daily").decode("utf-8", errors="ignore")
        # 按仓库卡片切块，每块取 slug / 描述 / 星标 / 今日新增 / 语言
        blocks = re.split(r'<article class="Box-row"[^>]*>', html)[1:]
        seen = set()
        for b in blocks:
            m = re.search(r'<h2\b[^>]*>.*?href="/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"', b, re.DOTALL)
            if not m or m.group(1) in seen:
                continue
            slug = m.group(1)
            seen.add(slug)
            d = re.search(r'class="[^"]*col-9[^"]*"[^>]*>\s*(.*?)\s*</p>', b, re.DOTALL)
            desc = clean_html(d.group(1)) if d else ""
            st = re.search(r'href="/[^"]+/stargazers"[^>]*>(.*?)</a>', b, re.DOTALL)
            stars = clean_html(st.group(1)) if st else ""
            td = re.search(r'([\d,]+)\s*stars today', b)
            lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', b)
            # 表里没有 stars / language 列，拼在摘要末尾（前端按「｜ ★ …」解析）
            extra = " · ".join(x for x in [
                f"★ {stars}" if stars else "", f"今日 +{td.group(1)}" if td else "", lang.group(1).strip() if lang else ""] if x)
            name = slug.replace("/", " / ")
            summary = (desc or f"GitHub 热门仓库：{name}") + (f" ｜ {extra}" if extra else "")
            items.append(make_item(
                categorize(name, desc), name,
                "GitHub Trending", summary,
                f"https://github.com/{slug}"
            ))
            if len(items) >= limit:
                break
    except Exception as e:
        print(f"  error: {e}")
    print(f"  {len(items)} items")
    return items


def fetch_arxiv(limit=8):
    print("→ arXiv cs.AI")
    items = []
    try:
        root    = ET.fromstring(fetch_url("https://rss.arxiv.org/rss/cs.AI"))
        channel = root.find("channel")
        for entry in (channel.findall("item") if channel is not None else [])[:limit]:
            title = (entry.findtext("title") or "").strip()
            link_el = entry.find("link")
            link = ""
            if link_el is not None:
                link = (link_el.text or "").strip()
                if not link and link_el.tail:
                    link = link_el.tail.strip()
            desc = truncate(re.sub(r"^\s*arXiv:\S+\s+Announce Type:\s*\S+\s*Abstract:\s*", "",
                                   clean_html(entry.findtext("description") or "")))
            if title:
                items.append(make_item("A", title, "arXiv", desc, link))
    except Exception as e:
        print(f"  error: {e}")
    print(f"  {len(items)} items")
    return items


def fetch_rss(feed_url, source_name, limit=8):
    print(f"→ {source_name}")
    items = []
    try:
        root    = ET.fromstring(fetch_url(feed_url))
        channel = root.find("channel")
        for entry in (channel.findall("item") if channel is not None else [])[:limit]:
            title = re.sub(r"\s+", " ", entry.findtext("title") or "").strip()
            link_el = entry.find("link")
            link = ""
            if link_el is not None:
                link = (link_el.text or "").strip()
                if not link and link_el.tail:
                    link = link_el.tail.strip()
            raw_desc = html.unescape(entry.findtext("description") or "")
            content  = html.unescape(entry.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "")
            desc = truncate(raw_desc) or truncate(content)
            image_url = None
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_desc + content)
            if m and m.group(1).startswith("http"):
                image_url = m.group(1)
            enc = entry.find("enclosure")
            if enc is not None and (enc.get("type","").startswith("image")):
                image_url = enc.get("url")
            media = entry.find("{http://search.yahoo.com/mrss/}content")
            if media is not None:
                image_url = media.get("url") or image_url
            if title:
                items.append(make_item(categorize(title, desc), title, source_name, desc, link, image_url))
    except Exception as e:
        print(f"  error: {e}")
    print(f"  {len(items)} items")
    return items

def fetch_36kr(limit=10):
    """36氪热榜（RSS 已被人机验证拦截，改用网页端热榜接口）"""
    print("→ 36氪")
    items = []
    try:
        body = json.dumps({"partner_id": "wap", "param": {"siteId": 1, "platformId": 2}}).encode()
        req  = urllib.request.Request(
            "https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot",
            data=body, headers={**UA, "Content-Type": "application/json"}, method="POST",
        )
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        for row in (data.get("data") or {}).get("hotRankList", [])[:limit]:
            m     = row.get("templateMaterial") or {}
            title = (m.get("widgetTitle") or "").strip()
            if not title:
                continue
            summary = truncate(m.get("summary") or m.get("widgetContent") or title)
            url     = f"https://36kr.com/p/{row.get('itemId') or m.get('itemId')}"
            items.append(make_item(categorize(title, summary), title, "36氪", summary, url, m.get("widgetImage")))
    except Exception as e:
        print(f"  error: {e}")
    print(f"  {len(items)} items")
    return items


# ── Supabase ──────────────────────────────────────────────────────────────────

def insert(items):
    if not items:
        return
    body = json.dumps(items).encode()
    req  = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/news_items?on_conflict=title",
        data=body,
        headers={
            "apikey":        ANON_KEY,
            "Authorization": f"Bearer {ANON_KEY}",
            "Content-Type":  "application/json",
            "Prefer":        "resolution=ignore-duplicates,return=minimal",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        print(f"\n✓ 写入成功，状态 {resp.status}，共 {len(items)} 条")
    except urllib.error.HTTPError as e:
        print(f"\n✗ Supabase 错误 {e.code}: {e.read().decode()[:300]}")


def db_count():
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/news_items?select=count",
        headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}", "Prefer": "count=exact"},
    )
    return urllib.request.urlopen(req).headers.get("content-range","?").split("/")[-1]

# ── 国内 RSS 源（地址, 显示名, 条数） ─────────────────────────────────────────

CN_FEEDS = [
    ("https://www.ithome.com/rss/",        "IT之家",   10),
    ("https://sspai.com/feed",             "少数派",    8),
    ("https://www.ifanr.com/feed",         "爱范儿",    8),
    ("https://www.qbitai.com/feed",        "量子位",    8),
    ("https://www.geekpark.net/rss",       "极客公园",  8),
    ("https://www.tmtpost.com/rss.xml",    "钛媒体",    8),
    ("https://www.leiphone.com/feed",      "雷峰网",    8),
    ("https://www.oschina.net/news/rss",   "开源中国",  8),
    ("https://www.infoq.cn/feed",          "InfoQ",     8),
]

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Scraper running — {TODAY}\n")
    all_items  = []
    all_items += fetch_hn()
    all_items += fetch_devto()
    all_items += fetch_github_trending()
    all_items += fetch_arxiv()
    # 国内媒体
    all_items += fetch_36kr()
    for feed_url, name, limit in CN_FEEDS:
        all_items += fetch_rss(feed_url, name, limit)
    # 同一标题只保留第一次出现（Supabase 以 title 去重，同批重复会报错）
    seen, uniq = set(), []
    for it in all_items:
        if it["title"] not in seen:
            seen.add(it["title"])
            uniq.append(it)
    all_items = uniq
    print(f"\n总计抓取 {len(all_items)} 条")
    insert(all_items)
    print(f"数据库当前共 {db_count()} 条")
