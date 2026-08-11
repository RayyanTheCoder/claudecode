#!/usr/bin/env python3
"""Generate PWA icons for MetaStrip. Pure-geometric, no external assets."""
from PIL import Image, ImageDraw

ACCENT = (124, 108, 255)      # #7c6cff
ACCENT_2 = (167, 139, 250)    # lighter violet
BG_TOP = (18, 18, 24)
BG_BOT = (28, 26, 40)
WHITE = (245, 245, 250)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_icon(px, maskable=False):
    ss = 4  # supersample
    S = px * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # vertical gradient background
    for y in range(S):
        d.line([(0, y), (S, y)], fill=lerp(BG_TOP, BG_BOT, y / S) + (255,))

    # rounded-square mask for the tile (non-maskable gets rounded corners)
    if not maskable:
        radius = int(S * 0.22)
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=radius, fill=255)
        img.putalpha(mask)
        d = ImageDraw.Draw(img)

    # safe area: maskable icons need content within the central 80%
    pad = S * (0.30 if maskable else 0.24)
    box = [pad, pad, S - pad, S - pad]
    bw = box[2] - box[0]
    bh = box[3] - box[1]

    # film frame (rounded rect outline)
    fx0 = box[0] + bw * 0.05
    fy0 = box[1] + bh * 0.16
    fx1 = box[2] - bw * 0.05
    fy1 = box[3] - bh * 0.16
    stroke = max(2, int(S * 0.018))
    d.rounded_rectangle([fx0, fy0, fx1, fy1], radius=int(bw * 0.10),
                        outline=ACCENT, width=stroke)

    # sprocket holes on the left rail
    rail_w = (fx1 - fx0) * 0.13
    hole_w = rail_w * 0.55
    n = 4
    for i in range(n):
        cy = fy0 + (fy1 - fy0) * (i + 0.5) / n
        hx = fx0 + rail_w * 0.5
        d.rounded_rectangle([hx - hole_w / 2, cy - hole_w / 2,
                             hx + hole_w / 2, cy + hole_w / 2],
                            radius=int(hole_w * 0.3), fill=ACCENT_2)

    # play triangle centered in the screen area
    cx = fx0 + rail_w + (fx1 - (fx0 + rail_w)) * 0.5
    cy = (fy0 + fy1) / 2
    tri = (fy1 - fy0) * 0.26
    d.polygon([(cx - tri * 0.7, cy - tri), (cx - tri * 0.7, cy + tri),
               (cx + tri * 0.9, cy)], fill=WHITE)

    # "strip" slash — a bold accent diagonal cutting across, with a gap for legibility
    sx0, sy0 = box[0] + bw * 0.14, box[3] - bh * 0.02
    sx1, sy1 = box[2] - bw * 0.02, box[1] + bh * 0.14
    d.line([(sx0, sy0), (sx1, sy1)], fill=(BG_TOP + (255,)), width=int(stroke * 3.4))
    d.line([(sx0, sy0), (sx1, sy1)], fill=ACCENT_2, width=int(stroke * 1.6))

    return img.resize((px, px), Image.LANCZOS)


def main():
    draw_icon(192).save("icons/icon-192.png")
    draw_icon(512).save("icons/icon-512.png")
    draw_icon(512, maskable=True).save("icons/icon-maskable-512.png")
    draw_icon(180).save("icons/apple-touch-icon.png")
    # favicon
    draw_icon(32).save("icons/favicon-32.png")
    print("icons written")


if __name__ == "__main__":
    main()
