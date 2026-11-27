#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多引擎精简搜索（搜狗移动版 / 360），只输出标题/链接/摘要。"""
import re, json, argparse, sys
import requests
from bs4 import BeautifulSoup

UA_M = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
UA_D = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
HEAD = {"Accept-Language": "zh-CN,zh;q=0.9"}


def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def real_url(href):
    """从搜狗跳转链接中取出真实 URL。"""
    if not href:
        return ""
    m = re.search(r"[?&]url=([^&]+)", href)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    return href


def parse_sogou_m(html, limit):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for h in soup.find_all("h3"):
        title = clean(h.get_text())
        if not title or len(title) < 4:
            continue
        box = h.parent
        for _ in range(3):
            if box and box.find("a"):
                break
            box = box.parent if box else None
        a = box.find("a") if box else None
        href = a.get("href") if a else ""
        if href and href.startswith("/"):
            href = "https://wap.sogou.com" + href
        txt = clean(box.get_text(" ")) if box else ""
        summary = txt.replace(title, "", 1)[:200]
        out.append({"title": title, "url": real_url(href), "summary": summary})
        if len(out) >= limit:
            break
    return out


def parse_so(html, limit):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for h in soup.find_all("h3"):
        a = h.find("a")
        if not a:
            continue
        title = clean(a.get_text())
        href = a.get("href", "")
        box = h.parent
        txt = clean(box.get_text(" ")) if box else ""
        summary = txt.replace(title, "", 1)[:220]
        out.append({"title": title, "url": real_url(href), "summary": summary})
        if len(out) >= limit:
            break
    return out


def run(q, limit=10, engine="sogou"):
    if engine == "sogou":
        r = requests.get("https://wap.sogou.com/web/searchList.jsp",
                         params={"keyword": q}, headers={"User-Agent": UA_M, **HEAD}, timeout=25)
        r.encoding = "utf-8"
        return parse_sogou_m(r.text, limit)
    else:
        r = requests.get("https://www.so.com/s", params={"q": q},
                         headers={"User-Agent": UA_D, **HEAD}, timeout=25)
        r.encoding = "utf-8"
        return parse_so(r.text, limit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--engine", default="sogou", choices=["sogou", "so"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        res = run(a.query, a.limit, a.engine)
    except Exception as e:
        print("ERR", e); return
    if not res and a.engine == "sogou":
        res = run(a.query, a.limit, "so")
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"### {a.query} -> {len(res)}")
    for i, x in enumerate(res, 1):
        print(f"[{i}] {x['title']}\n    {x['url']}\n    {x['summary']}")


if __name__ == "__main__":
    main()