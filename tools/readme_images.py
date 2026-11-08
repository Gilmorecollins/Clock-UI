#!/usr/bin/env python3
"""
Renders the README graphics into docs/images/ from the generated assets.

Run tools/generate.py first (this reads its drawables and watchface.xml), then:

    python tools/readme_images.py
"""

from __future__ import annotations

import os
import re

from PIL import Image, ImageDraw, ImageFont

import generate as g

OUT = os.path.join(g.HERE, "..", "docs", "images")
BG = (17, 19, 21)
CARD = (26, 29, 31)
WHITE = (255, 255, 255)
MUTED = (154, 160, 163)
ACCENT = g.COMET_COLOR


# --------------------------------------------------------------------------
# Face renderer (mirrors draw_preview, but with any time / steps / battery,
# and an ambient mode)
# --------------------------------------------------------------------------

def boxes() -> dict[str, tuple[int, int, int, int]]:
    """Placement of every PartImage, read back from the generated XML."""
    xml = open(os.path.join(g.RAW, "watchface.xml"), encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'<PartImage name="(\w+)" x="(-?\d+)" y="(-?\d+)"\s+width="(\d+)" height="(\d+)"',
                         xml):
        name, x, y, w, h = m.group(1), *map(int, m.groups()[1:])
        out[name] = (x, y, x + w, y + h)
    return out


BOX = None


def drawable(name: str, alpha: int = 255) -> Image.Image:
    img = Image.open(os.path.join(g.DRAWABLE, name + ".png")).convert("RGBA")
    if alpha < 255:
        img.putalpha(img.getchannel("A").point(lambda v: v * alpha // 255))
    return img


def centred(d: ImageDraw.ImageDraw, text: str, cx: float, cy: float, size: int, fill: tuple) -> None:
    f = ImageFont.truetype(g.FONT_PATH, size)
    b = d.textbbox((0, 0), text, font=f)
    d.text((cx - (b[0] + b[2]) / 2, cy - (b[1] + b[3]) / 2), text, font=f, fill=fill)


def face(hour: int = 16, minute: int = 42, second: int = 10, steps: int = 6482,
         goal: int = 10000, battery: int = 78, ambient: bool = False) -> Image.Image:
    img = Image.new("RGBA", (g.SIZE, g.SIZE), (0, 0, 0, 255))
    dial = g.AMBIENT_DIAL_ALPHA if ambient else 255
    txt = g.AMBIENT_TEXT_ALPHA if ambient else 255

    def rotated(name: str, degrees: float) -> Image.Image:
        layer = Image.new("RGBA", (g.SIZE, g.SIZE), (0, 0, 0, 0))
        layer.alpha_composite(drawable(name), BOX[name][:2])
        return layer.rotate(-degrees, resample=Image.BICUBIC)

    if not ambient:
        img.alpha_composite(drawable("ticks_seconds"))
        lit = "tick_lit_major" if second % 5 == 0 else "tick_lit_minor"
        img.alpha_composite(rotated(lit, 6 * second))
        img.alpha_composite(rotated("comet", 6 * second))

    off = (g.SIZE - g.MIN_IMG) // 2
    img.alpha_composite(drawable("ticks_minutes", dial), (off, off))
    img.alpha_composite(drawable("pill", txt), BOX["pill"][:2])

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if not ambient:
        for i in range(0, 60, 5):
            k = g.label_glow(i, second)
            c = tuple(round(255 + (a - 255) * k) for a in g.COMET_COLOR)
            centred(d, str(i), *g.polar(g.SEC_NUM_RADIUS, 6 * i), g.SEC_NUM_SIZE, c + (255,))
    f = ImageFont.truetype(g.FONT_PATH, g.HOUR_SIZE)
    b = d.textbbox((0, 0), f"{hour:02d}", font=f)
    d.text((g.HOUR_RIGHT - b[2], g.HOUR_CY - (b[1] + b[3]) / 2), f"{hour:02d}", font=f,
           fill=(255, 255, 255, txt))
    centred(d, f"{minute:02d}", g.MINUTE_CX, g.MINUTE_CY, g.MINUTE_SIZE, (255, 255, 255, txt))
    img.alpha_composite(layer)

    # Steps and battery, dimmed as one group in ambient.
    grp = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(grp)
    centred(gd, str(steps), g.CX, g.STEPS_COUNT_CY, g.STEPS_COUNT_SIZE, (255, 255, 255, 255))
    grp.alpha_composite(drawable("steps_label"), BOX["steps_label"][:2])
    pct = 100 * steps / goal
    k = next(k for k in range(len(g.STEPS_TIERS)) if g.steps_tier(k, pct))
    grp.alpha_composite(drawable(f"steps_icon_{k}"), BOX[f"steps_icon_{k}"][:2])

    low = battery <= g.BATTERY_LOW_PERCENT
    for s in range(g.BATTERY_SEGMENTS):
        name = ("battery_seg_low" if low else "battery_seg_on") if g.battery_lit(s, battery) \
            else "battery_seg_track"
        grp.alpha_composite(drawable(name), BOX[f"battery_{s}_track"][:2])
    centred(gd, f"{battery}%", g.CX, g.BATTERY_TEXT_CY, g.BATTERY_TEXT_SIZE,
            (g.BATTERY_LOW_COLOR if low else g.BATTERY_TEXT_COLOR) + (255,))
    if ambient:
        grp.putalpha(grp.getchannel("A").point(lambda v: v * g.STEPS_AMBIENT_ALPHA // 255))
    img.alpha_composite(grp)
    return img


def round_mask(img: Image.Image) -> Image.Image:
    """Clip to the round screen, over the card colour."""
    ss = 4
    mask = Image.new("L", (img.width * ss, img.height * ss), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, mask.width - 1, mask.height - 1], fill=255)
    mask = mask.resize(img.size, Image.LANCZOS)
    out = Image.new("RGBA", img.size, CARD + (255,))
    out.paste(img, (0, 0), mask)
    return out


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(g.FONT_PATH, size)


def card(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=24, fill=CARD)
    return img, d


def save(img: Image.Image, name: str) -> None:
    path = os.path.join(OUT, name)
    img.save(path)
    print(f"  {name}  {img.width}x{img.height}")


# --------------------------------------------------------------------------
# The graphics
# --------------------------------------------------------------------------

def features() -> None:
    """The face with every element called out; new ones tagged NEW."""
    W, H, FX, FY = 1300, 560, 425, 55
    img, d = card(W, H)
    img.alpha_composite(round_mask(face()), (FX, FY))

    def p(x: float, y: float) -> tuple[float, float]:
        return FX + x, FY + y

    left = [
        ("Step count", "today's total, from Samsung Health", p(g.CX - 52, g.STEPS_COUNT_CY), 120, True),
        ("Icon colour", "shows progress to your daily goal", p(g.CX - 40, g.STEPS_LABEL_CY), 215, True),
        ("Hour", "follows the watch's 12/24h setting", p(126, g.HOUR_CY), 310, False),
        ("Battery", "5 segments + %, red at 15% and below", p(g.CX - 55, g.BATTERY_SEG_CY), 420, True),
    ]
    right = [
        ("Lit tick + label glow", "light cyan as the comet passes", p(*g.polar(g.SEC_NUM_RADIUS, 60)), 110, False),
        ("Seconds comet", "the only moving part; glides", p(*g.polar(g.COMET_TRACK_RADIUS, 60)), 205, False),
        ("Minute pill", "", p(g.PILL_RIGHT - 6, g.MINUTE_CY), 300, False),
        ("Inner ring", "stays, dimmed, in always-on", p(*g.polar(g.MIN_TICK_OUTER - 4, 125)), 410, False),
    ]

    title, sub = font(19), font(14)

    def callout(name, desc, pt, ly, new, side):
        x_edge = 385 if side == "L" else W - 385
        d.line([pt, (x_edge, ly)], fill=MUTED + (255,), width=1)
        r = 4
        d.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=ACCENT if new else WHITE)
        tw = d.textlength(name, font=title)
        tag_w = 46 if new else 0
        if side == "L":
            tx = x_edge - 10 - tw - tag_w
            dx = x_edge - 10 - d.textlength(desc, font=sub)
        else:
            tx = x_edge + 10
            dx = x_edge + 10
        d.text((tx, ly - 22), name, font=title, fill=WHITE)
        if new:
            nx = tx + tw + 8
            d.rounded_rectangle([nx, ly - 20, nx + 38, ly - 3], radius=8, fill=ACCENT)
            d.text((nx + 19, ly - 11.5), "NEW", font=font(11), fill=(0, 0, 0), anchor="mm")
        if desc:
            d.text((dx, ly + 2), desc, font=sub, fill=MUTED)

    for c in left:
        callout(*c, side="L")
    for c in right:
        callout(*c, side="R")
    save(img, "features.png")


def steps_stages() -> None:
    examples = [1240, 3810, 6482, 8930, 10214]
    names = ["Grey", "Orange", "Yellow", "Cyan", "Green"]
    meaning = ["just started", "warming up", "halfway", "nearly there", "goal reached"]
    ranges = ["0–24%", "25–49%", "50–74%", "75–99%", "100%+"]
    TW, TH, PAD = 200, 210, 16
    img, d = card(PAD + 5 * (TW + PAD), TH + 2 * PAD)
    for i, n in enumerate(examples):
        x = PAD + i * (TW + PAD)
        # Tight enough that no inner-ring tick reaches the corners.
        crop = face(steps=n).crop((g.CX - 64, 112, g.CX + 64, 176)).resize((TW, 100), Image.LANCZOS)
        d.rounded_rectangle([x, PAD, x + TW, PAD + 105], radius=16, fill=(0, 0, 0))
        img.alpha_composite(crop, (x, PAD + 3))
        color = g.STEPS_TIERS[i][1]
        d.text((x + TW / 2, PAD + 132), names[i], font=font(18), fill=color, anchor="mm")
        d.text((x + TW / 2, PAD + 158), meaning[i], font=font(14), fill=WHITE, anchor="mm")
        d.text((x + TW / 2, PAD + 182), f"{ranges[i]} of goal", font=font(13), fill=MUTED, anchor="mm")
    save(img, "steps-stages.png")


def battery_states() -> None:
    levels = [100, 78, 50, 12, 3]
    titles = ["Full", "Normal", "Half", "Low", "Nearly empty"]
    notes = ["all five segments", "filled to the nearest fifth", "", "red at 15% and below",
             "one segment stays lit from 1%"]
    TW, PAD = 200, 16
    img, d = card(PAD + 5 * (TW + PAD), 190)
    for i, lvl in enumerate(levels):
        x = PAD + i * (TW + PAD)
        crop = face(battery=lvl).crop((g.CX - 70, 284, g.CX + 70, 338)).resize((TW, 77), Image.LANCZOS)
        d.rounded_rectangle([x, PAD, x + TW, PAD + 105], radius=16, fill=(0, 0, 0))
        img.alpha_composite(crop, (x, PAD + 14))
        d.text((x + TW / 2, PAD + 132), titles[i], font=font(18), fill=WHITE, anchor="mm")
        if notes[i]:
            d.text((x + TW / 2, PAD + 156), notes[i], font=font(13), fill=MUTED, anchor="mm")
    save(img, "battery-states.png")


def modes() -> None:
    S, PAD = 380, 30
    img, d = card(3 * PAD + 2 * S, S + 2 * PAD + 40)
    for i, (amb, label) in enumerate(((False, "Interactive"), (True, "Always-on"))):
        x = PAD + i * (S + PAD)
        img.alpha_composite(round_mask(face(ambient=amb).resize((S, S), Image.LANCZOS)), (x, PAD))
        d.text((x + S / 2, PAD + S + 24), label, font=font(18), fill=WHITE, anchor="mm")
    save(img, "modes.png")


def on_watch(src: str | None) -> None:
    """Frame a real screenshot from the watch, if one is given."""
    if not src or not os.path.exists(src):
        return
    shot = Image.open(src).convert("RGBA")
    S, PAD = 360, 30
    img, d = card(S + 2 * PAD, S + 2 * PAD + 40)
    img.alpha_composite(round_mask(shot.resize((S, S), Image.LANCZOS)), (PAD, PAD))
    d.text((PAD + S / 2, PAD + S + 24), "Galaxy Watch 4 · 40mm", font=font(16), fill=MUTED,
           anchor="mm")
    save(img, "on-watch.png")


def main() -> None:
    global BOX
    import sys
    os.makedirs(OUT, exist_ok=True)
    BOX = boxes()
    print("readme images:")
    features()
    steps_stages()
    battery_states()
    modes()
    on_watch(sys.argv[1] if len(sys.argv) > 1 else None)


if __name__ == "__main__":
    main()
