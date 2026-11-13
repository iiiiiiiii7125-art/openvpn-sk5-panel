#!/usr/bin/env python3
"""渲染级对比度自检：按 WCAG 相对亮度算 index.html 调色板的对比度.

底线 4.5（正文），目标 7。玻璃卡按白 72% 叠在 #f6f7fb 上估算有效底色
#fbfcfe；顶栏/侧栏白 70% 同理。跑法：python3 contrast-check.py
"""
import sys


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg, bg):
    l1, l2 = sorted((lum(fg), lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def blend(fg_hex, bg_hex, alpha):
    f = [int(fg_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(bg_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(round(alpha * x + (1 - alpha) * y)
                                   for x, y in zip(f, b))


GLASS = blend("#ffffff", "#f6f7fb", 0.72)  # 卡片白 72% 叠底色
PAIRS = [
    ("正文 #1f2937 / 玻璃卡", "#1f2937", GLASS, 4.5),
    ("次要文字 #4b5563 / 玻璃卡", "#4b5563", GLASS, 4.5),
    ("主按钮白字 / #2563eb", "#ffffff", "#2563eb", 4.5),
    ("次按钮白字 / #4b5563", "#ffffff", "#4b5563", 4.5),
    ("危险按钮白字 / #b91c1c", "#ffffff", "#b91c1c", 4.5),
    ("成功绿字 #15803d / 玻璃卡", "#15803d", GLASS, 4.5),
    ("徽标绿字 #166534 / #dcfce7", "#166534", "#dcfce7", 4.5),
    ("徽标红字 #991b1b / #fee2e2", "#991b1b", "#fee2e2", 4.5),
    ("激活导航 #1e40af / 激活底", "#1e40af", blend("#ffffff", GLASS, 0.60), 4.5),
    ("链接 #1d4ed8 / 玻璃卡", "#1d4ed8", GLASS, 4.5),
]


def main():
    print("玻璃卡有效底色: %s" % GLASS)
    failed = 0
    for name, fg, bg, floor in PAIRS:
        r = ratio(fg, bg)
        mark = "PASS" if r >= floor else "FAIL"
        if r < floor:
            failed += 1
        print("%-28s %s on %s  ratio=%.2f  floor=%.1f  %s"
              % (name, fg, bg, r, floor, mark))
    print("目标 7 达成数: %d/%d" % (sum(1 for _, fg, bg, _ in PAIRS
                                        if ratio(fg, bg) >= 7.0), len(PAIRS)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
