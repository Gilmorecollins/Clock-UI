#!/usr/bin/env python3
"""
Generates the Radial Clock watch face assets and res/raw/watchface.xml.

Design source: design/mockups/radial-clock-comet-concept.png. Geometry below was
measured from that 1254px mockup (face radius 596px) and scaled to the 450x450
canvas Wear OS designs against.

The face is almost entirely static:

  * outer ring  -- 60 white ticks (one PNG) plus 12 static second labels
  * inner ring  -- 60 dim grey ticks (one PNG), no labels
  * centre      -- the hour, and the minute inside a filled rounded pill
  * battery     -- five segments and the percentage under the time
  * comet       -- the only moving part: a cyan dot with a fading tail, one small
                   cropped PNG inside a Group that rotates with the seconds

Run:  python tools/generate.py
"""

from __future__ import annotations

import math
import os
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# Geometry.  All values are in canvas units on the 450x450 design surface.
# --------------------------------------------------------------------------

SIZE = 450
CX = CY = SIZE / 2

DIAL_TEXT = "#ffffff"

# Outer ring: seconds, in "bezel" style. The ticks run right out to the screen
# edge and the labels sit just inside them. (The original mockup had the labels
# outside the ticks, but then the labels hold the edge and the face can't fill
# a small round screen: on the 40mm Galaxy Watch 4 it left a black band.)
# Every tick hangs inward from the same outer circle, so the face's silhouette is
# one clean circle; the five-second ticks reach further in and are thicker.
# (Staggered tips -- long ticks to the edge, short ones stopping short -- made the
# edge read as a jagged polygon.) The outer circle sits a few units inside the
# canvas so the round panel never crops it.
SEC_TICK_OUTER = 220
SEC_TICK_MINOR_INNER = 209
SEC_TICK_MAJOR_INNER = 200
SEC_TICK_MINOR_WIDTH = 2.4
SEC_TICK_MAJOR_WIDTH = 4.5
SEC_TICK_COLOR = (255, 255, 255, 240)
SEC_NUM_RADIUS = 182
SEC_NUM_HEIGHT = 17                 # rendered digit height, px
SEC_IMG = 450                       # ticks reach the edge, so the full canvas

# Inner ring: plain grey ticks, no labels. Built like the outer ring: every tick
# hangs inward from one outer circle, so the tips facing the comet form a clean
# circle; the five-minute ticks reach further in.
MIN_TICK_OUTER = 146
MIN_TICK_MINOR_INNER = 137
MIN_TICK_MAJOR_INNER = 132
MIN_TICK_MINOR_WIDTH = 2.0
MIN_TICK_MAJOR_WIDTH = 2.4
MIN_TICK_MINOR_COLOR = (255, 255, 255, 80)
MIN_TICK_MAJOR_COLOR = (255, 255, 255, 140)
MIN_IMG = 294

# Hour: always two digits (09, not 9), right-aligned with the mockup's 15px gap to
# the pill. The mockup's 94px digits only fit a narrow hour like "16"; wide ones
# ("00", "08", "09") would spill over the inner ring. So the size is the largest up
# to the mockup's at which EVERY hour 00-23 keeps HOUR_RING_MARGIN clear of it.
HOUR_RIGHT = 237.5
HOUR_CY = 227
HOUR_MAX_HEIGHT = 94                # the mockup's rendered digit height, px
HOUR_RING_MARGIN = 10               # min gap between hour ink and the inner ring

# Minute pill: a filled, fully closed rounded rectangle.
PILL_LEFT = 253
PILL_RIGHT = 342
PILL_TOP = 192
PILL_BOTTOM = 258
PILL_RADIUS = 20
PILL_COLOR = (36, 39, 40, 255)      # #242728
# Centred in the pill (the mockup's digits sit ~2px high; centred reads better).
MINUTE_CX = (PILL_LEFT + PILL_RIGHT) / 2
MINUTE_CY = (PILL_TOP + PILL_BOTTOM) / 2
MINUTE_HEIGHT = 38                  # rendered digit height, px

# WFF positions text by font metrics (advance width, line box), not by visible ink,
# so a PartText box placed at the ink target lands a few px off. These offsets were
# measured on the emulator and move the boxes so the INK lands on the targets above.
HOUR_NUDGE = (3.5, 1)              # ink ended 3.6px short of HOUR_RIGHT, 1px high
MINUTE_NUDGE = (-0.5, 0.5)         # ink sat ~0.5px right and 0.5px high

# Comet (seconds indicator), drawn pointing at 12 o'clock and rotated at runtime.
COMET_COLOR = (11, 225, 253)        # #0BE1FD
COMET_TAIL_COLOR = (4, 60, 70)      # dark teal the tail fades into
# The comet runs along the centre of the gap between the inner ring and the second
# labels, so the dot has an even margin to both. Computed after the fonts are sized
# (see comet_track_radius) so it stays centred if either moves.
COMET_DOT_SIZE = 15
COMET_TAIL_DEGREES = 25
COMET_TAIL_MAX_WIDTH = 8

# Lit tick: the outer tick for the current second turns cyan as the comet reaches
# it, stepping once per second. Drawn slightly wider than the white tick so no
# white fringe shows round its antialiased edges.
LIT_TICK_EXTRA_WIDTH = 0.8

# Label glow: each second label (0, 5, 10...) flashes the comet's colour as the
# comet reaches it, then fades back to white over this many seconds. At 5 a label
# has just faded out as the comet lights the next one.
LABEL_GLOW_SECONDS = 5

# Battery: five short segments under the time, filled to the nearest fifth, with
# the exact percentage underneath. Reads the watch's own [BATTERY_PERCENT] rather
# than a ComplicationSlot, so there is no slot for the runtime to reject. Segments
# and number turn red at BATTERY_LOW_PERCENT and below.
BATTERY = True
BATTERY_SEGMENTS = 5
BATTERY_SEG_WIDTH = 9
BATTERY_SEG_HEIGHT = 6
BATTERY_SEG_GAP = 3
BATTERY_SEG_CY = 304
BATTERY_TEXT_CY = 319
BATTERY_TEXT_SIZE = 12              # font size (em), as WFF takes it
BATTERY_TRACK_COLOR = (60, 64, 66)
BATTERY_TEXT_COLOR = (150, 155, 158)
BATTERY_LOW_COLOR = (255, 92, 77)
BATTERY_LOW_PERCENT = 15
BATTERY_AMBIENT_ALPHA = 200
PREVIEW_BATTERY = 78

SS = 4                              # supersampling factor for antialiasing

# SECOND_MILLISECOND makes the comet glide continuously instead of ticking. Set it
# to "SECOND" for a once-per-second step, which is much cheaper (~1fps).
SECONDS_SOURCE = "SECOND_MILLISECOND"

# Without a frame-rate hint, the runtime presents the face at exactly 10.0fps -- a
# flat 100ms cadence on a 60Hz panel, which makes a glide read as stutter.
#
# <Sweep> is the only explicit frame-rate request in the format. It is defined for
# AnalogClock hands rather than Groups, so this adds a completely invisible swept
# second hand purely as a hint -- and the rate it unlocks applies to the whole
# surface, so the comet gets it too.
#
# Measured on the Galaxy Watch 4 with the old rotating-dial design, screen on:
#     no hint          10.0 fps   (flat 100ms cadence)
#     frequency=15     20.2 fps
#     frequency=60     24.6 fps   (p50 gap 33ms, many frames at a single vsync)
# 0% janky frames in every case. SYNC_TO_DEVICE has not been measured yet.
#
# WFF accepts 2, 5, 10, 15, or SYNC_TO_DEVICE. The latter lets the runtime draw
# as quickly as the device can while keeping the sweep smooth. Set
# FRAME_RATE_HINT = False to return to the stock rate, which draws less power.
FRAME_RATE_HINT = True
SWEEP_FREQUENCY = "SYNC_TO_DEVICE"

# Ambient alphas. The quality bar (WO-P7) is 15% *mean luminance* across the face,
# and this design is nearly all black, so there is plenty of headroom.
#
# The comet goes dark in ambient because ambient only refreshes once a minute, so
# it would sit frozen on a stale second. The outer ring goes with it: without the
# comet it carries no information, and dropping it keeps the always-on display
# calm and low-burn. The inner ring, hour and minute stay.
AMBIENT_DIAL_ALPHA = 160
AMBIENT_TEXT_ALPHA = 230

# Burn-in protection. Measured on this watch, nothing shifts the face in ambient:
# two AOD frames 75s apart (which differ elsewhere, so the capture was live) put
# the hour glyphs on pixel-identical coordinates. The hour sits at alpha 230 in
# the same place for a whole hour at a time, which is how OLEDs get ghosted.
#
# So nudge the entire face around a small lattice, one step per minute. Deliberately
# integer modular arithmetic rather than sin/cos: WFF's docs do not say whether its
# trig takes degrees or radians, and this needs no such assumption.
#
#   x = [MINUTE] % 5 - 2                 -> -2..+2
#   y = floor([MINUTE] / 5) % 5 - 2      -> -2..+2
#
# 25 distinct positions, so the load spreads over ~25px2 instead of burning one
# fixed set. At +/-2px it is imperceptible in either mode. The only things near the
# edge are the outer labels, which are hidden in ambient anyway.
BURN_IN_DRIFT = True

PREVIEW_TIME = (16, 42, 10)         # matches the mockup

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "watchface", "src", "main", "res")
DRAWABLE = os.path.join(RES, "drawable")
RAW = os.path.join(RES, "raw")
FONT_DIR = os.path.join(RES, "font")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def polar(radius: float, degrees: float) -> tuple[float, float]:
    """Canvas coordinates at `radius` from centre, `degrees` clockwise from 12 o'clock."""
    rad = math.radians(degrees)
    return CX + radius * math.sin(rad), CY - radius * math.cos(rad)


# Google Sans Flex Bold, matching the mockup. Only the Bold instance is bundled.
FONT_FAMILY = "google_sans_flex"


FONT_PATH = os.path.join(FONT_DIR, "google_sans_flex_bold.ttf")


def fit_font_size(sample: str, digit_height: float) -> int:
    """Smallest font size whose rendered `sample` is at least `digit_height` px tall.

    The mockup was measured in rendered pixels, but WFF takes an em size, so this
    converts using the actual font's glyph metrics.
    """
    for size in range(6, 400):
        top, bottom = ImageFont.truetype(FONT_PATH, size).getbbox(sample)[1::2]
        if bottom - top >= digit_height:
            return size
    raise ValueError(sample)


SEC_NUM_SIZE = fit_font_size("0", SEC_NUM_HEIGHT)
def hour_ink_radius(size: int) -> float:
    """Furthest any hour 00-23 reaches from the centre, drawn as the face places it."""
    f = ImageFont.truetype(FONT_PATH, size)
    worst = 0.0
    for h in range(24):
        text = f"{h:02d}"
        x0, y0, x1, y1 = f.getbbox(text)
        mask = f.getmask(text)                      # ink only, origin at (x0, y0)
        left = HOUR_RIGHT - (x1 - x0)
        top = HOUR_CY - (y1 - y0) / 2
        w, hgt = mask.size
        for my in range(hgt):
            for mx in range(w):
                if mask.getpixel((mx, my)) > 64:
                    worst = max(worst, math.hypot(left + mx - CX, top + my - CY))
    return worst


def fit_hour_size() -> int:
    size = fit_font_size("16", HOUR_MAX_HEIGHT)
    while hour_ink_radius(size) > MIN_TICK_MAJOR_INNER - HOUR_RING_MARGIN:
        size -= 1
    return size


HOUR_SIZE = fit_hour_size()
MINUTE_SIZE = fit_font_size("42", MINUTE_HEIGHT)

def label_inner_radius() -> float:
    """Closest any second label's ink box comes to the centre."""
    f = ImageFont.truetype(FONT_PATH, SEC_NUM_SIZE)
    nearest = float(SEC_NUM_RADIUS)
    for i in range(0, 60, 5):
        x, y = polar(SEC_NUM_RADIUS, 6 * i)
        x0, y0, x1, y1 = f.getbbox(str(i))
        hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
        # Nearest point of the label's box to the centre.
        nx = max(abs(x - CX) - hw, 0)
        ny = max(abs(y - CY) - hh, 0)
        nearest = min(nearest, math.hypot(nx, ny))
    return nearest


COMET_TRACK_RADIUS = (MIN_TICK_OUTER + label_inner_radius()) / 2
COMET_DOT_RADIUS = COMET_TRACK_RADIUS
COMET_TAIL_RADIUS = COMET_TRACK_RADIUS


def save_cropped(img_ss: Image.Image, path: str) -> tuple[int, int, int, int]:
    """Downsample a supersampled full-canvas layer, crop it to its content, save it.

    Returns the placement box. Small layers are much cheaper to composite on every
    frame than full-canvas ones.
    """
    full = img_ss.resize((SIZE, SIZE), Image.LANCZOS)
    box = full.getbbox()
    full.crop(box).save(path)
    x0, y0, x1, y1 = box
    print(f"  {os.path.basename(path)}  {x1 - x0}x{y1 - y0} at ({x0},{y0})")
    return box


def rounded_line(d: ImageDraw.ImageDraw, p0: tuple[float, float], p1: tuple[float, float],
                 width: float, fill: tuple) -> None:
    """A line with round caps (ImageDraw only draws square ends). Coordinates in SS px.

    p0 and p1 are where the INK ends, caps included: the centreline is shortened by
    half the width at each end. Otherwise wide ticks overshoot narrow ones by the
    difference in their cap radii and the tips no longer meet a common circle.
    """
    r = width / 2
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    ux, uy = (p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length
    p0 = (p0[0] + ux * r, p0[1] + uy * r)
    p1 = (p1[0] - ux * r, p1[1] - uy * r)
    d.line([p0, p1], fill=fill, width=max(1, round(width)))
    for x, y in (p0, p1):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def draw_ring(path: str, box: int,
              minor_span: tuple[float, float], major_span: tuple[float, float],
              minor_width: float, major_width: float,
              minor_color: tuple, major_color: tuple) -> None:
    """Render the 60 ticks of one ring into a square PNG centred on the canvas centre.

    Spans are (inner, outer) radii of the ink, round caps included.
    """
    img = Image.new("RGBA", (box * SS, box * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    off = (SIZE - box) / 2          # canvas coords -> image coords

    for i in range(60):
        major = i % 5 == 0
        inner, outer = major_span if major else minor_span
        x0, y0 = polar(inner, 6 * i)
        x1, y1 = polar(outer, 6 * i)
        rounded_line(d, ((x0 - off) * SS, (y0 - off) * SS), ((x1 - off) * SS, (y1 - off) * SS),
                     (major_width if major else minor_width) * SS,
                     major_color if major else minor_color)

    img.resize((box, box), Image.LANCZOS).save(path)
    print(f"  {os.path.basename(path)}  {box}x{box}")


def draw_pill(path: str) -> tuple[int, int, int, int]:
    """The minute pill: a filled rounded rectangle."""
    img = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [PILL_LEFT * SS, PILL_TOP * SS, PILL_RIGHT * SS, PILL_BOTTOM * SS],
        radius=PILL_RADIUS * SS, fill=PILL_COLOR,
    )
    return save_cropped(img, path)


def draw_comet(path: str) -> tuple[int, int, int, int]:
    """The seconds comet pointing at 12 o'clock: fading tail, stem and dot."""
    img = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Tail: overlapping discs from the faint end to the head. ImageDraw overwrites
    # rather than blends, so each brighter disc cleanly replaces the one behind it.
    steps = 160
    for n in range(steps + 1):
        t = n / steps                               # 0 = tail end, 1 = head
        x, y = polar(COMET_TAIL_RADIUS, -COMET_TAIL_DEGREES * (1 - t))
        r = (0.6 + (COMET_TAIL_MAX_WIDTH / 2 - 0.6) * t ** 1.2) * SS
        color = tuple(round(a + (b - a) * t ** 1.5) for a, b in zip(COMET_TAIL_COLOR, COMET_COLOR))
        alpha = round(255 * min(1.0, 0.15 + t ** 1.3))
        d.ellipse([x * SS - r, y * SS - r, x * SS + r, y * SS + r], fill=color + (alpha,))

    x0, y0 = polar(COMET_DOT_RADIUS, 0)
    r = COMET_DOT_SIZE / 2 * SS
    d.ellipse([x0 * SS - r, y0 * SS - r, x0 * SS + r, y0 * SS + r], fill=COMET_COLOR + (255,))

    return save_cropped(img, path)


def draw_lit_tick(path: str, inner: float, width: float) -> tuple[int, int, int, int]:
    """A cyan copy of one outer tick at 12 o'clock, rotated to the current second at runtime."""
    img = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    x0, y0 = polar(inner, 0)
    x1, y1 = polar(SEC_TICK_OUTER, 0)
    rounded_line(ImageDraw.Draw(img), (x0 * SS, y0 * SS), (x1 * SS, y1 * SS),
                 (width + LIT_TICK_EXTRA_WIDTH) * SS, COMET_COLOR + (255,))
    return save_cropped(img, path)


def battery_seg_left() -> float:
    """Canvas x of the first segment's left edge, centring the row on the face."""
    total = BATTERY_SEGMENTS * BATTERY_SEG_WIDTH + (BATTERY_SEGMENTS - 1) * BATTERY_SEG_GAP
    return CX - total / 2


def draw_battery_segment(path: str, color: tuple) -> tuple[int, int]:
    """One rounded segment, padded by a pixel and offset so its subpixel position is
    right. Every segment shares the same fractional x, so one image serves all five.

    Returns the integer canvas offset of the image for the FIRST segment; segment k
    sits BATTERY_SEG_WIDTH + BATTERY_SEG_GAP further right per step.
    """
    left = battery_seg_left()
    top = BATTERY_SEG_CY - BATTERY_SEG_HEIGHT / 2
    ox, oy = math.floor(left) - 1, math.floor(top) - 1
    w = math.ceil(left - ox + BATTERY_SEG_WIDTH + 1)
    h = math.ceil(top - oy + BATTERY_SEG_HEIGHT + 1)
    img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    x0, y0 = (left - ox) * SS, (top - oy) * SS
    ImageDraw.Draw(img).rounded_rectangle(
        [x0, y0, x0 + BATTERY_SEG_WIDTH * SS, y0 + BATTERY_SEG_HEIGHT * SS],
        radius=BATTERY_SEG_HEIGHT / 2 * SS, fill=color + (255,))
    img.resize((w, h), Image.LANCZOS).save(path)
    print(f"  {os.path.basename(path)}  {w}x{h}")
    return ox, oy


def battery_threshold(k: int) -> int:
    """Percent at which segment k (0-based) lights: the level rounded to fifths,
    but never fewer than one segment while there is any charge."""
    return max(1, 20 * (k + 1) - 10)


def battery_lit(k: int, pct: int) -> bool:
    """Python twin of battery_on_expr(), for the preview."""
    return pct >= battery_threshold(k)


def battery_on_expr(k: int) -> str:
    """1 when segment k is lit, else 0. floor((pct + 100 - t) / 100) is 0 below the
    threshold t and 1 from it up to 100%: pure arithmetic, no comparison operator
    (see OFF_FIVE for why)."""
    return f"floor(([BATTERY_PERCENT] + {100 - battery_threshold(k)}) / 100)"


# 1 at BATTERY_LOW_PERCENT and below, 0 above. Same trick as battery_on_expr().
BATTERY_LOW_EXPR = f"(1 - floor(([BATTERY_PERCENT] + {99 - BATTERY_LOW_PERCENT}) / 100))"


def draw_blank(path: str) -> None:
    """A 2x2 transparent pixel for the invisible frame-rate hint hand to point at."""
    Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(path)
    print(f"  {os.path.basename(path)}  2x2")


def draw_preview(path: str, hour: int, minute: int, second: int,
                 pill_box: tuple[int, int, int, int],
                 comet_box: tuple[int, int, int, int],
                 lit_boxes: dict[str, tuple[int, int, int, int]],
                 battery_origin: tuple[int, int]) -> None:
    """A static render of the face for the watch face picker."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))

    for name, box in (("ticks_seconds.png", SEC_IMG), ("ticks_minutes.png", MIN_IMG)):
        layer = Image.open(os.path.join(DRAWABLE, name)).convert("RGBA")
        off = int((SIZE - box) / 2)
        img.alpha_composite(layer, (off, off))

    def rotated(name: str, box: tuple[int, int, int, int], degrees: float) -> Image.Image:
        layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        layer.alpha_composite(Image.open(os.path.join(DRAWABLE, name + ".png")).convert("RGBA"),
                              box[:2])
        return layer.rotate(-degrees, resample=Image.BICUBIC)

    lit = "tick_lit_major" if second % 5 == 0 else "tick_lit_minor"
    img.alpha_composite(rotated(lit, lit_boxes[lit], 6 * second))
    img.alpha_composite(rotated("comet", comet_box, 6 * second))

    img.alpha_composite(Image.open(os.path.join(DRAWABLE, "pill.png")).convert("RGBA"),
                        pill_box[:2])

    d = ImageDraw.Draw(img)

    def centred(text: str, cx: float, cy: float, size: int,
                fill: tuple = (255, 255, 255, 255), draw: ImageDraw.ImageDraw | None = None) -> None:
        draw = draw or d
        f = ImageFont.truetype(FONT_PATH, size)
        box = draw.textbbox((0, 0), text, font=f)
        draw.text((cx - (box[0] + box[2]) / 2, cy - (box[1] + box[3]) / 2), text, font=f,
                  fill=fill)

    for i in range(0, 60, 5):
        xy = polar(SEC_NUM_RADIUS, 6 * i)
        centred(str(i), *xy, SEC_NUM_SIZE)
        # The glow as the watch draws it at this second: a cyan copy blended on top.
        k = label_glow(i, second)
        if k > 0:
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            centred(str(i), *xy, SEC_NUM_SIZE, COMET_COLOR + (255,), ImageDraw.Draw(layer))
            layer.putalpha(layer.getchannel("A").point(lambda v: round(v * k)))
            img.alpha_composite(layer)

    f = ImageFont.truetype(FONT_PATH, HOUR_SIZE)
    box = d.textbbox((0, 0), f"{hour:02d}", font=f)
    d.text((HOUR_RIGHT - box[2], HOUR_CY - (box[1] + box[3]) / 2), f"{hour:02d}", font=f,
           fill=(255, 255, 255, 255))

    centred(f"{minute:02d}", MINUTE_CX, MINUTE_CY, MINUTE_SIZE)

    if BATTERY:
        pct = PREVIEW_BATTERY
        low = pct <= BATTERY_LOW_PERCENT
        on_name = "battery_seg_low" if low else "battery_seg_on"
        ox, oy = battery_origin
        for k in range(BATTERY_SEGMENTS):
            name = on_name if battery_lit(k, pct) else "battery_seg_track"
            seg = Image.open(os.path.join(DRAWABLE, name + ".png")).convert("RGBA")
            img.alpha_composite(seg, (ox + k * (BATTERY_SEG_WIDTH + BATTERY_SEG_GAP), oy))
        centred(f"{pct}%", CX, BATTERY_TEXT_CY, BATTERY_TEXT_SIZE,
                (BATTERY_LOW_COLOR if low else BATTERY_TEXT_COLOR) + (255,))

    img.convert("RGB").save(path)
    print(f"  {os.path.basename(path)}  {SIZE}x{SIZE}")


# --------------------------------------------------------------------------
# watchface.xml
# --------------------------------------------------------------------------

def label_glow(label: int, second: float) -> float:
    """Glow strength 0..1 of a second label: 1 as the comet arrives, fading to 0.

    The Python twin of label_glow_expr(), used for the preview.
    """
    since = (second - label + 60) % 60
    lit = 1 - math.floor((since + 60 - LABEL_GLOW_SECONDS) / 60)
    return lit * (1 - since / LABEL_GLOW_SECONDS)


def label_glow_expr(label: int) -> str:
    """WFF alpha expression for a label's glow copy.

    `since` is how long ago the comet passed the label, 0..60s. floor((since + 60 -
    G) / 60) is 0 while since < G and 1 after, so the glow is on only for the first
    G seconds, ramping 255 -> 0. Pure arithmetic: on this watch's v1 runtime a
    comparison operator froze the face (see OFF_FIVE).
    """
    g = LABEL_GLOW_SECONDS
    since = f"(([{SECONDS_SOURCE}] - {label} + 60) % 60)"
    return f"255 * (1 - floor(({since} + {60 - g}) / 60)) * (1 - {since} / {g})"


def second_labels(indent: str) -> str:
    """One static PartText per 5-second label, 0 at 12 o'clock, each with a cyan
    copy on top that glows as the comet passes (label_glow_expr)."""
    box_w, box_h = 36, 30
    comet_hex = "#{:02x}{:02x}{:02x}".format(*COMET_COLOR)
    out = []
    for i in range(0, 60, 5):
        x, y = polar(SEC_NUM_RADIUS, 6 * i)
        for name, color, alpha in ((f"second_label_{i}", DIAL_TEXT, None),
                                   (f"second_label_{i}_glow", comet_hex, label_glow_expr(i))):
            transform = (f'\n{indent}  <Transform target="alpha" value="{alpha}" />'
                         if alpha else "")
            out.append(f"""{indent}<PartText name="{name}"
{indent}          x="{round(x - box_w / 2)}" y="{round(y - box_h / 2)}"
{indent}          width="{box_w}" height="{box_h}">{transform}
{indent}  <Text align="CENTER">
{indent}    <Font family="{FONT_FAMILY}" size="{SEC_NUM_SIZE}" weight="BOLD" color="{color}">{i}</Font>
{indent}  </Text>
{indent}</PartText>""")
    return "\n".join(out)


def centred_image(name: str, resource: str, box: int, indent: str) -> str:
    xy = round((SIZE - box) / 2)
    return f"""{indent}<PartImage name="{name}" x="{xy}" y="{xy}" width="{box}" height="{box}">
{indent}  <Image resource="{resource}" />
{indent}</PartImage>"""


# 0 on a five-second mark (0, 5, 10...), 1 on every other second. Deliberately pure
# arithmetic: on this watch's v1 runtime an expression using a comparison
# ("[SECOND] % 5 == 0 ? 255 : 0") silently froze the whole face after its first frame.
OFF_FIVE = "floor(([SECOND] % 5 + 4) / 5)"


def lit_tick_image(name: str, box: tuple[int, int, int, int], alpha: str,
                   indent: str) -> str:
    return f"""{indent}<PartImage name="{name}" x="{box[0]}" y="{box[1]}"
{indent}           width="{box[2] - box[0]}" height="{box[3] - box[1]}">
{indent}  <Transform target="alpha" value="{alpha}" />
{indent}  <Image resource="{name}" />
{indent}</PartImage>"""


def battery_xml(origin: tuple[int, int], indent: str = "    ") -> str:
    """Five segments (track, cyan or red by arithmetic alpha) and the percentage."""
    if not BATTERY:
        return ""
    hexc = lambda c: "#{:02x}{:02x}{:02x}".format(*c)
    ox, oy = origin
    seg = Image.open(os.path.join(DRAWABLE, "battery_seg_track.png"))
    w, h = seg.size
    i2 = indent + "  "
    parts = []
    for k in range(BATTERY_SEGMENTS):
        x = ox + k * (BATTERY_SEG_WIDTH + BATTERY_SEG_GAP)
        on = battery_on_expr(k)
        for name, res, alpha in (
                (f"battery_{k}_track", "battery_seg_track", None),
                (f"battery_{k}_on", "battery_seg_on", f"255 * {on} * (1 - {BATTERY_LOW_EXPR})"),
                (f"battery_{k}_low", "battery_seg_low", f"255 * {on} * {BATTERY_LOW_EXPR}")):
            transform = (f'\n{i2}  <Transform target="alpha" value="{alpha}" />' if alpha else "")
            parts.append(f"""{i2}<PartImage name="{name}" x="{x}" y="{oy}" width="{w}" height="{h}">{transform}
{i2}  <Image resource="{res}" />
{i2}</PartImage>""")
    box_w, box_h = 70, 30
    for name, color, alpha in (("battery_percent", BATTERY_TEXT_COLOR, f"255 * (1 - {BATTERY_LOW_EXPR})"),
                               ("battery_percent_low", BATTERY_LOW_COLOR, f"255 * {BATTERY_LOW_EXPR}")):
        parts.append(f"""{i2}<PartText name="{name}" x="{round(CX - box_w / 2)}" y="{round(BATTERY_TEXT_CY - box_h / 2)}"
{i2}          width="{box_w}" height="{box_h}">
{i2}  <Transform target="alpha" value="{alpha}" />
{i2}  <Text align="CENTER">
{i2}    <Font family="{FONT_FAMILY}" size="{BATTERY_TEXT_SIZE}" weight="BOLD" color="{hexc(color)}">
{i2}      <Template>%d%%<Parameter expression="[BATTERY_PERCENT]" /></Template>
{i2}    </Font>
{i2}  </Text>
{i2}</PartText>""")
    body = "\n".join(parts)
    return f"""
{indent}<!-- Battery: five segments filled to the nearest fifth, the percentage under
{indent}     them. Cyan normally, red at {BATTERY_LOW_PERCENT}% and below. -->
{indent}<Group name="battery" x="0" y="0" width="{SIZE}" height="{SIZE}">
{indent}  <Variant mode="AMBIENT" target="alpha" value="{BATTERY_AMBIENT_ALPHA}" />
{body}
{indent}</Group>
"""


def build_xml(pill_box: tuple[int, int, int, int], comet_box: tuple[int, int, int, int],
              lit_boxes: dict[str, tuple[int, int, int, int]],
              battery_origin: tuple[int, int]) -> str:
    hour_box_w = 220
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!--
  Radial Clock - generated by tools/generate.py, do not hand-edit.
  Edit the constants in that script and re-run it instead.
-->
<WatchFace width="{SIZE}" height="{SIZE}" clipShape="CIRCLE">

  <Metadata key="CLOCK_TYPE" value="DIGITAL" />
  <Metadata key="PREVIEW_TIME" value="{PREVIEW_TIME[0]:02d}:{PREVIEW_TIME[1]:02d}:{PREVIEW_TIME[2]:02d}" />

  <Scene backgroundColor="#000000">

    <!-- Outer ring, lit tick and comet sit OUTSIDE the burn-in drift. They are all
         hidden in ambient, so drift protects nothing there, and the outer ring hugs
         the round screen edge: drifting it 2px makes the edge gap visibly uneven. -->

    <!-- Outer ring: static ticks and labels. Hidden in ambient along with the comet. -->
    <Group name="outer_ring" x="0" y="0" width="{SIZE}" height="{SIZE}">
      <Variant mode="AMBIENT" target="alpha" value="0" />
{centred_image("seconds_ticks", "ticks_seconds", SEC_IMG, "      ")}
{second_labels("      ")}
    </Group>

    <!-- Lit tick: the outer tick for the current second turns cyan, stepping once a
         second as the comet reaches it. Long tick on 0, 5, 10..., short otherwise. -->
    <Group name="lit_tick" x="0" y="0" width="{SIZE}" height="{SIZE}"
           pivotX="0.5" pivotY="0.5">
      <Variant mode="AMBIENT" target="alpha" value="0" />
      <Transform target="angle" value="6 * [SECOND]" />
{lit_tick_image("tick_lit_major", lit_boxes["tick_lit_major"], f"255 - 255 * {OFF_FIVE}", "      ")}
{lit_tick_image("tick_lit_minor", lit_boxes["tick_lit_minor"], f"255 * {OFF_FIVE}", "      ")}
    </Group>

    <!-- The comet: the only continuously moving part. A small cropped image inside a full-canvas
         Group, so the rotation pivots on the face centre but only the comet's own
         pixels are composited each frame. -->
    <Group name="seconds_comet" x="0" y="0" width="{SIZE}" height="{SIZE}"
           pivotX="0.5" pivotY="0.5">
      <Variant mode="AMBIENT" target="alpha" value="0" />
      <Transform target="angle" value="6 * [{SECONDS_SOURCE}]" />
      <PartImage name="comet" x="{comet_box[0]}" y="{comet_box[1]}"
                 width="{comet_box[2] - comet_box[0]}" height="{comet_box[3] - comet_box[1]}">
        <Image resource="comet" />
      </PartImage>
    </Group>
{drift_open()}
    <!-- Inner ring: static grey ticks, kept (dimmed) in ambient. -->
    <Group name="inner_ring" x="0" y="0" width="{SIZE}" height="{SIZE}">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_DIAL_ALPHA}" />
{centred_image("minutes_ticks", "ticks_minutes", MIN_IMG, "      ")}
    </Group>

    <!-- Hour, right-aligned against the minute pill. Follows the wearer's
         12/24-hour setting. -->
    <PartText name="hour" x="{round(HOUR_RIGHT + HOUR_NUDGE[0]) - hour_box_w}" y="{round(HOUR_CY + HOUR_NUDGE[1] - 70)}"
              width="{hour_box_w}" height="140">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_TEXT_ALPHA}" />
      <Text align="END">
        <Font family="{FONT_FAMILY}" size="{HOUR_SIZE}" weight="BOLD" color="#ffffff">
          <Template>%02d<Parameter expression="[IS_24_HOUR_MODE] ? [HOUR_0_23] : [HOUR_1_12]" /></Template>
        </Font>
      </Text>
    </PartText>

    <PartImage name="pill" x="{pill_box[0]}" y="{pill_box[1]}"
               width="{pill_box[2] - pill_box[0]}" height="{pill_box[3] - pill_box[1]}">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_TEXT_ALPHA}" />
      <Image resource="pill" />
    </PartImage>

    <PartText name="minute" x="{round(MINUTE_CX + MINUTE_NUDGE[0]) - 45}" y="{round(MINUTE_CY + MINUTE_NUDGE[1]) - 35}"
              width="90" height="70">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_TEXT_ALPHA}" />
      <Text align="CENTER">
        <Font family="{FONT_FAMILY}" size="{MINUTE_SIZE}" weight="BOLD" color="#ffffff">
          <Template>%02d<Parameter expression="[MINUTE]" /></Template>
        </Font>
      </Text>
    </PartText>
{battery_xml(battery_origin)}{frame_rate_probe()}
{drift_close()}
  </Scene>
</WatchFace>
"""


def drift_open() -> str:
    """Open the burn-in drift group that carries the whole face."""
    if not BURN_IN_DRIFT:
        return ""
    return f"""
    <!-- Burn-in protection: nudges the whole face around a 5x5 one-pixel lattice,
         one step per minute. Nothing on this watch shifts the face otherwise. -->
    <Group name="burn_in_drift" x="0" y="0" width="{SIZE}" height="{SIZE}">
      <Transform target="x" value="[MINUTE] % 5 - 2" />
      <Transform target="y" value="floor([MINUTE] / 5) % 5 - 2" />
"""


def drift_close() -> str:
    return "    </Group>" if BURN_IN_DRIFT else ""


def frame_rate_probe() -> str:
    """An invisible swept second hand, present only to ask for a higher frame rate.

    It draws nothing (alpha="0"); <Sweep> is simply the one lever WFF exposes for
    frame rate, and it happens to lift the whole surface rather than just the hand.
    """
    if not FRAME_RATE_HINT:
        return ""
    return f"""
    <AnalogClock x="0" y="0" width="450" height="450">
      <SecondHand resource="blank" x="224" y="120" width="2" height="105"
                  pivotX="0.5" pivotY="1.0" alpha="0">
        <Sweep frequency="{SWEEP_FREQUENCY}" />
      </SecondHand>
    </AnalogClock>
"""


def main() -> None:
    os.makedirs(DRAWABLE, exist_ok=True)
    os.makedirs(RAW, exist_ok=True)

    print(f"font sizes: labels {SEC_NUM_SIZE}, hour {HOUR_SIZE}, minute {MINUTE_SIZE}")
    print(f"comet track radius: {COMET_TRACK_RADIUS:.1f}")
    print("assets:")
    draw_ring(os.path.join(DRAWABLE, "ticks_seconds.png"), SEC_IMG,
              (SEC_TICK_MINOR_INNER, SEC_TICK_OUTER), (SEC_TICK_MAJOR_INNER, SEC_TICK_OUTER),
              SEC_TICK_MINOR_WIDTH, SEC_TICK_MAJOR_WIDTH, SEC_TICK_COLOR, SEC_TICK_COLOR)
    draw_ring(os.path.join(DRAWABLE, "ticks_minutes.png"), MIN_IMG,
              (MIN_TICK_MINOR_INNER, MIN_TICK_OUTER), (MIN_TICK_MAJOR_INNER, MIN_TICK_OUTER),
              MIN_TICK_MINOR_WIDTH, MIN_TICK_MAJOR_WIDTH,
              MIN_TICK_MINOR_COLOR, MIN_TICK_MAJOR_COLOR)
    pill_box = draw_pill(os.path.join(DRAWABLE, "pill.png"))
    comet_box = draw_comet(os.path.join(DRAWABLE, "comet.png"))
    lit_boxes = {
        "tick_lit_major": draw_lit_tick(os.path.join(DRAWABLE, "tick_lit_major.png"),
                                        SEC_TICK_MAJOR_INNER, SEC_TICK_MAJOR_WIDTH),
        "tick_lit_minor": draw_lit_tick(os.path.join(DRAWABLE, "tick_lit_minor.png"),
                                        SEC_TICK_MINOR_INNER, SEC_TICK_MINOR_WIDTH),
    }
    battery_origin = (0, 0)
    if BATTERY:
        for name, color in (("battery_seg_track", BATTERY_TRACK_COLOR),
                            ("battery_seg_on", COMET_COLOR),
                            ("battery_seg_low", BATTERY_LOW_COLOR)):
            battery_origin = draw_battery_segment(os.path.join(DRAWABLE, name + ".png"), color)
    draw_blank(os.path.join(DRAWABLE, "blank.png"))
    draw_preview(os.path.join(DRAWABLE, "preview.png"), *PREVIEW_TIME, pill_box, comet_box,
                 lit_boxes, battery_origin)

    xml_path = os.path.join(RAW, "watchface.xml")
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(build_xml(pill_box, comet_box, lit_boxes, battery_origin))
    print(f"\nwatchface.xml written to {os.path.relpath(xml_path, HERE)}")


if __name__ == "__main__":
    main()
