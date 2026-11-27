#!/usr/bin/env python3
"""生成小红书笔记配图（4 张，1080x1440）。"""

import os
from PIL import Image, ImageDraw, ImageFont

OUT = "/workspace/xhs_images"
os.makedirs(OUT, exist_ok=True)

W, H = 1080, 1440
BG = "#F7F1E6"
INK = "#2B2B2B"
MUTED = "#6B6258"
ORANGE = "#E86A33"
BLUE = "#3A6EA5"
GREEN = "#4F7A5A"
CARD = "#FFFDF8"
LINE = "#DED3C2"

FONT_BOLD = "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc"
FONT_REG = "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Medium.ttc"


def font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def new_canvas():
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def text(draw, xy, content, size, color=INK, bold=False, anchor="la", spacing=1.15):
    draw.multiline_text(xy, content, font=font(size, bold), fill=color, anchor=anchor, spacing=int(size * spacing))


def card(draw, box, fill=CARD, outline=LINE, radius=36, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def save(img, name):
    img.save(os.path.join(OUT, name), "PNG")


# ---------------- 1. 封面 ----------------
img, d = new_canvas()
d.rounded_rectangle((80, 70, 430, 130), radius=30, fill="#EFE3CF")
text(d, (255, 100), "出行游玩规划 Skill", 30, MUTED, anchor="mm")

text(d, (80, 250), "会算体力上限", 98, INK, bold=True)
text(d, (80, 380), "的旅行规划Skill", 84, ORANGE, bold=True)

d.line((80, 520, 1000, 520), fill=LINE, width=3)

text(d, (80, 590), "70岁父母 + 5岁娃", 54, INK, bold=True)
text(d, (80, 670), "一天只走 0.6km", 64, BLUE, bold=True)

card(d, (80, 820, 1000, 1020))
text(d, (120, 860), "输入", 34, MUTED)
text(d, (120, 910), "目的地 · 人数 · 年龄结构 · 想玩什么", 38, INK)

card(d, (80, 1050, 1000, 1250))
text(d, (120, 1090), "输出", 34, MUTED)
text(d, (120, 1140), "A 尽兴 / B 舒适 / C 省心", 42, ORANGE, bold=True)

text(d, (80, 1320), "搜「出行游玩规划」体验", 34, MUTED)
d.ellipse((930, 1290, 990, 1350), fill=ORANGE)
save(img, "01_cover.png")


# ---------------- 2. 年龄体力表 ----------------
img, d = new_canvas()
text(d, (80, 90), "年龄不是数字", 74, INK, bold=True)
text(d, (80, 190), "是体力上限", 74, ORANGE, bold=True)
text(d, (80, 300), "同样是 6km 基准，不同年龄的可走量差很多", 32, MUTED)

rows = [
    ("0–3 岁", "1–2 km", "0.25"),
    ("4–6 岁", "2–4 km", "0.50"),
    ("7–12 岁", "5–8 km", "1.08"),
    ("18–25 岁", "10–15 km", "2.08"),
    ("61–70 岁", "3–5 km", "0.67"),
    ("70+ 岁", "1.5–3 km", "0.40"),
]
top = 400
row_h = 110
card(d, (80, top, 1000, top + row_h * (len(rows) + 1) + 10), fill=CARD)
d.rounded_rectangle((80, top, 1000, top + row_h), radius=30, fill="#2B2B2B")
text(d, (110, top + 55), "年龄段", 36, "#FFFFFF", bold=True, anchor="lm")
text(d, (480, top + 55), "全天步行", 36, "#FFFFFF", bold=True, anchor="lm")
text(d, (800, top + 55), "系数", 36, "#FFFFFF", bold=True, anchor="lm")

for i, (age, walk, factor) in enumerate(rows):
    y = top + row_h * (i + 1)
    if i % 2 == 1:
        d.rectangle((82, y + 4, 998, y + row_h - 4), fill="#F3EADB")
    text(d, (110, y + 55), age, 36, INK, anchor="lm")
    text(d, (480, y + 55), walk, 36, INK, anchor="lm")
    text(d, (800, y + 55), factor, 38, BLUE, bold=True, anchor="lm")

card(d, (80, 1180, 1000, 1330), fill="#FDF1E8", outline="#F0C9B4")
text(d, (120, 1215), "组合人群：取最弱成员，再乘 0.85", 34, INK, bold=True)
text(d, (120, 1270), "熟练带娃带老人用 0.92，但硬约束不放松", 28, MUTED)
save(img, "02_age_table.png")


# ---------------- 3. ABC 对比 ----------------
img, d = new_canvas()
text(d, (80, 90), "同一趟成都", 74, INK, bold=True)
text(d, (80, 190), "三种走法", 74, ORANGE, bold=True)
text(d, (80, 300), "不是好中差，是三种场景的最优解", 32, MUTED)

cols = [
    ("A", "尽兴版", "4 个点", "1.11 km", "50%", "18:17", BLUE),
    ("B", "舒适版", "3 个点", "0.60 km", "67%", "16:50", ORANGE),
    ("C", "省心版", "2 个点", "0.60 km", "50%", "15:34", GREEN),
]
x0, y0, cw, ch, gap = 80, 400, 280, 720, 40
for i, (key, name, points, walk, indoor, end, color) in enumerate(cols):
    x = x0 + i * (cw + gap)
    card(d, (x, y0, x + cw, y0 + ch), fill=CARD)
    d.rounded_rectangle((x, y0, x + cw, y0 + 120), radius=36, fill=color)
    d.rectangle((x, y0 + 80, x + cw, y0 + 120), fill=color)
    text(d, (x + cw // 2, y0 + 58), key, 64, "#FFFFFF", bold=True, anchor="mm")
    text(d, (x + cw // 2, y0 + 165), name, 44, INK, bold=True, anchor="mm")
    labels = [("点位", points), ("步行", walk), ("室内", indoor), ("结束", end)]
    for j, (label, value) in enumerate(labels):
        yy = y0 + 285 + j * 100
        text(d, (x + 30, yy), label, 30, MUTED)
        text(d, (x + 30, yy + 40), value, 40, INK, bold=True)
    if key == "B":
        d.rounded_rectangle((x + 70, y0 + 205, x + cw - 70, y0 + 252), radius=22, fill="#FDF1E8")
        text(d, (x + cw // 2, y0 + 228), "推荐", 26, ORANGE, bold=True, anchor="mm")

card(d, (80, 1180, 1000, 1330), fill="#FDF1E8", outline="#F0C9B4")
text(d, (120, 1215), "B 舒适版：16:50 结束", 36, INK, bold=True)
text(d, (120, 1270), "0.6km 步行 + 90 分钟午休，老人孩子都走得完", 28, MUTED)
save(img, "03_abc_compare.png")


# ---------------- 4. 已上架 ----------------
img, d = new_canvas()
text(d, (80, 100), "已上架两个", 74, INK, bold=True)
text(d, (80, 200), "Skill 市场", 74, ORANGE, bold=True)
text(d, (80, 310), "搜「出行游玩规划」直接体验", 34, MUTED)

card(d, (80, 420, 1000, 680), fill=CARD)
d.rounded_rectangle((110, 455, 320, 505), radius=24, fill="#FFE8E0")
text(d, (215, 480), "小红书 Skill 市场", 26, ORANGE, bold=True, anchor="mm")
text(d, (110, 540), "搜「出行游玩规划」", 44, INK, bold=True)
text(d, (110, 610), "原创 · 效率工具 / 生活决策", 30, MUTED)

card(d, (80, 730, 1000, 990), fill=CARD)
d.rounded_rectangle((110, 765, 320, 815), radius=24, fill="#E6EEF8")
text(d, (215, 790), "华为云 Skill 市场", 26, BLUE, bold=True, anchor="mm")
text(d, (110, 850), "搜「city-trip-planner」", 40, INK, bold=True)
text(d, (110, 920), "通用场景 · 生活方式", 30, MUTED)

card(d, (80, 1070, 1000, 1250), fill="#2B2B2B")
text(d, (120, 1110), "它能做什么", 32, "#F7F1E6", bold=True)
text(d, (120, 1165), "真实美食 · 市井街区 · 商场 · ABC 路线", 32, "#FFFFFF")
save(img, "04_market.png")

print("generated:", sorted(os.listdir(OUT)))