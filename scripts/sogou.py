#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精简搜狗网页搜索：只输出 标题/链接/摘要，便于研究取用。"""
import sys, re, json, argparse, urllib.parse
import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
BASE = "https://www.sogou.com/web"


def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def search(q, pages=1, limit=10):
    out = []
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    for p in range(1, pages + 1):
        params = {"query": q}
        if p > 1:
            params["page"] = p
        r = s.get(BASE, params=params, timeout=25)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        blocks = soup.select("div.vrwrap") or soup.select("div.rb")
        for b in blocks:
            a = b.select_one("h3 a") or b.select_one("a.title")
            if not a:
                continue
            title = clean(a.get_text())
            href = a.get("href", "")
            if href.startswith("/link"):
                href = "https://www.sogou.com" + href
            snip = b.select_one(".str-text-info") or b.select_one(".text-layout") \
                or b.select_one(".str_info") or b.select_one(".ft")
            summary = clean(snip.get_text())[:220] if snip else ""
            src = b.select_one(".citeurl") or b.select_one("cite")
            source = clean(src.get_text()) if src else ""
            out.append({"title": title, "url": href, "source": source, "summary": summary})
            if len(out) >= limit:
                return out
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = search(a.query, a.pages, a.limit)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(f"### {a.query}  -> {len(res)} 条")
        for i, x in enumerate(res, 1):
            print(f"[{i}] {x['title']}")
            print(f"    {x['source']} | {x['url']}")
            print(f"    {x['summary']}")


if __name__ == "__main__":
    main()