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

# Outer ring: seconds.  Every tick starts at the same inner radius; the five-second
# ticks reach further out and are thicker.
SEC_TICK_INNER = 176
SEC_TICK_MINOR_OUTER = 186
SEC_TICK_MAJOR_OUTER = 193
SEC_TICK_MINOR_WIDTH = 2.0
SEC_TICK_MAJOR_WIDTH = 3.2
SEC_TICK_COLOR = (255, 255, 255, 240)
SEC_NUM_RADIUS = 206
SEC_NUM_HEIGHT = 15                 # rendered digit height, px
SEC_IMG = 392                       # tick image is cropped to the annulus it needs

# Inner ring: plain grey ticks, no labels.
MIN_TICK_INNER = 134
MIN_TICK_MINOR_OUTER = 143
MIN_TICK_MAJOR_OUTER = 147
MIN_TICK_MINOR_WIDTH = 2.0
MIN_TICK_MAJOR_WIDTH = 2.4
MIN_TICK_MINOR_COLOR = (255, 255, 255, 80)
MIN_TICK_MAJOR_COLOR = (255, 255, 255, 140)
MIN_IMG = 300

# Hour: right-aligned so one- and two-digit hours both sit snugly against the pill.
HOUR_RIGHT = 245
HOUR_CY = 227
HOUR_HEIGHT = 94                    # rendered digit height, px

# Minute pill: a filled, fully closed rounded rectangle.
PILL_LEFT = 253
PILL_RIGHT = 342
PILL_TOP = 192
PILL_BOTTOM = 258
PILL_RADIUS = 20
PILL_COLOR = (36, 39, 40, 255)      # #242728
MINUTE_CX = 297
MINUTE_CY = 223
MINUTE_HEIGHT = 38                  # rendered digit height, px

# Comet (seconds indicator), drawn pointing at 12 o'clock and rotated at runtime.
COMET_COLOR = (11, 225, 253)        # #0BE1FD
COMET_TAIL_COLOR = (4, 60, 70)      # dark teal the tail fades into
COMET_DOT_RADIUS = 170
COMET_DOT_SIZE = 15
COMET_LINE_OUTER = 193              # short stem out to the tips of the major ticks
COMET_LINE_WIDTH = 3
COMET_TAIL_RADIUS = 168
COMET_TAIL_DEGREES = 25
COMET_TAIL_MAX_WIDTH = 8

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
HOUR_SIZE = fit_font_size("16", HOUR_HEIGHT)
MINUTE_SIZE = fit_font_size("42", MINUTE_HEIGHT)


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


def draw_ring(path: str, box: int, inner: float, minor_outer: float, major_outer: float,
              minor_width: float, major_width: float,
              minor_color: tuple, major_color: tuple) -> None:
    """Render the 60 ticks of one ring into a square PNG centred on the canvas centre."""
    img = Image.new("RGBA", (box * SS, box * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    off = (SIZE - box) / 2          # canvas coords -> image coords

    for i in range(60):
        major = i % 5 == 0
        x0, y0 = polar(inner, 6 * i)
        x1, y1 = polar(major_outer if major else minor_outer, 6 * i)
        d.line(
            [((x0 - off) * SS, (y0 - off) * SS), ((x1 - off) * SS, (y1 - off) * SS)],
            fill=major_color if major else minor_color,
            width=max(1, round((major_width if major else minor_width) * SS)),
        )

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
    x1, y1 = polar(COMET_LINE_OUTER, 0)
    d.line([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=COMET_COLOR + (255,),
           width=COMET_LINE_WIDTH * SS)
    r = COMET_DOT_SIZE / 2 * SS
    d.ellipse([x0 * SS - r, y0 * SS - r, x0 * SS + r, y0 * SS + r], fill=COMET_COLOR + (255,))

    return save_cropped(img, path)


def draw_blank(path: str) -> None:
    """A 2x2 transparent pixel for the invisible frame-rate hint hand to point at."""
    Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(path)
    print(f"  {os.path.basename(path)}  2x2")


def draw_preview(path: str, hour: int, minute: int, second: int,
                 pill_box: tuple[int, int, int, int],
                 comet_box: tuple[int, int, int, int]) -> None:
    """A static render of the face for the watch face picker."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))

    for name, box in (("ticks_seconds.png", SEC_IMG), ("ticks_minutes.png", MIN_IMG)):
        layer = Image.open(os.path.join(DRAWABLE, name)).convert("RGBA")
        off = int((SIZE - box) / 2)
        img.alpha_composite(layer, (off, off))

    comet = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    comet.alpha_composite(Image.open(os.path.join(DRAWABLE, "comet.png")).convert("RGBA"),
                          comet_box[:2])
    img.alpha_composite(comet.rotate(-6 * second, resample=Image.BICUBIC))

    img.alpha_composite(Image.open(os.path.join(DRAWABLE, "pill.png")).convert("RGBA"),
                        pill_box[:2])

    d = ImageDraw.Draw(img)

    def centred(text: str, cx: float, cy: float, size: int) -> None:
        f = ImageFont.truetype(FONT_PATH, size)
        box = d.textbbox((0, 0), text, font=f)
        d.text((cx - (box[0] + box[2]) / 2, cy - (box[1] + box[3]) / 2), text, font=f,
               fill=(255, 255, 255, 255))

    for i in range(0, 60, 5):
        centred(str(i), *polar(SEC_NUM_RADIUS, 6 * i), SEC_NUM_SIZE)

    f = ImageFont.truetype(FONT_PATH, HOUR_SIZE)
    box = d.textbbox((0, 0), str(hour), font=f)
    d.text((HOUR_RIGHT - box[2], HOUR_CY - (box[1] + box[3]) / 2), str(hour), font=f,
           fill=(255, 255, 255, 255))

    centred(f"{minute:02d}", MINUTE_CX, MINUTE_CY, MINUTE_SIZE)

    img.convert("RGB").save(path)
    print(f"  {os.path.basename(path)}  {SIZE}x{SIZE}")


# --------------------------------------------------------------------------
# watchface.xml
# --------------------------------------------------------------------------

def second_labels(indent: str) -> str:
    """One static PartText per 5-second label, 0 at 12 o'clock."""
    box_w, box_h = 36, 30
    out = []
    for i in range(0, 60, 5):
        x, y = polar(SEC_NUM_RADIUS, 6 * i)
        out.append(f"""{indent}<PartText name="second_label_{i}"
{indent}          x="{round(x - box_w / 2)}" y="{round(y - box_h / 2)}"
{indent}          width="{box_w}" height="{box_h}">
{indent}  <Text align="CENTER">
{indent}    <Font family="{FONT_FAMILY}" size="{SEC_NUM_SIZE}" weight="BOLD" color="{DIAL_TEXT}">{i}</Font>
{indent}  </Text>
{indent}</PartText>""")
    return "\n".join(out)


def centred_image(name: str, resource: str, box: int, indent: str) -> str:
    xy = round((SIZE - box) / 2)
    return f"""{indent}<PartImage name="{name}" x="{xy}" y="{xy}" width="{box}" height="{box}">
{indent}  <Image resource="{resource}" />
{indent}</PartImage>"""


def build_xml(pill_box: tuple[int, int, int, int], comet_box: tuple[int, int, int, int]) -> str:
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
{drift_open()}
    <!-- Outer ring: static ticks and labels. Hidden in ambient along with the comet. -->
    <Group name="outer_ring" x="0" y="0" width="{SIZE}" height="{SIZE}">
      <Variant mode="AMBIENT" target="alpha" value="0" />
{centred_image("seconds_ticks", "ticks_seconds", SEC_IMG, "      ")}
{second_labels("      ")}
    </Group>

    <!-- Inner ring: static grey ticks, kept (dimmed) in ambient. -->
    <Group name="inner_ring" x="0" y="0" width="{SIZE}" height="{SIZE}">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_DIAL_ALPHA}" />
{centred_image("minutes_ticks", "ticks_minutes", MIN_IMG, "      ")}
    </Group>

    <!-- The comet: the only moving part. A small cropped image inside a full-canvas
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

    <!-- Hour, right-aligned against the minute pill. Follows the wearer's
         12/24-hour setting. -->
    <PartText name="hour" x="{HOUR_RIGHT - hour_box_w}" y="{round(HOUR_CY - 70)}"
              width="{hour_box_w}" height="140">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_TEXT_ALPHA}" />
      <Text align="END">
        <Font family="{FONT_FAMILY}" size="{HOUR_SIZE}" weight="BOLD" color="#ffffff">
          <Template>%d<Parameter expression="[IS_24_HOUR_MODE] ? [HOUR_0_23] : [HOUR_1_12]" /></Template>
        </Font>
      </Text>
    </PartText>

    <PartImage name="pill" x="{pill_box[0]}" y="{pill_box[1]}"
               width="{pill_box[2] - pill_box[0]}" height="{pill_box[3] - pill_box[1]}">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_TEXT_ALPHA}" />
      <Image resource="pill" />
    </PartImage>

    <PartText name="minute" x="{MINUTE_CX - 45}" y="{MINUTE_CY - 35}"
              width="90" height="70">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_TEXT_ALPHA}" />
      <Text align="CENTER">
        <Font family="{FONT_FAMILY}" size="{MINUTE_SIZE}" weight="BOLD" color="#ffffff">
          <Template>%02d<Parameter expression="[MINUTE]" /></Template>
        </Font>
      </Text>
    </PartText>
{frame_rate_probe()}
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
    print("assets:")
    draw_ring(os.path.join(DRAWABLE, "ticks_seconds.png"), SEC_IMG,
              SEC_TICK_INNER, SEC_TICK_MINOR_OUTER, SEC_TICK_MAJOR_OUTER,
              SEC_TICK_MINOR_WIDTH, SEC_TICK_MAJOR_WIDTH, SEC_TICK_COLOR, SEC_TICK_COLOR)
    draw_ring(os.path.join(DRAWABLE, "ticks_minutes.png"), MIN_IMG,
              MIN_TICK_INNER, MIN_TICK_MINOR_OUTER, MIN_TICK_MAJOR_OUTER,
              MIN_TICK_MINOR_WIDTH, MIN_TICK_MAJOR_WIDTH,
              MIN_TICK_MINOR_COLOR, MIN_TICK_MAJOR_COLOR)
    pill_box = draw_pill(os.path.join(DRAWABLE, "pill.png"))
    comet_box = draw_comet(os.path.join(DRAWABLE, "comet.png"))
    draw_blank(os.path.join(DRAWABLE, "blank.png"))
    draw_preview(os.path.join(DRAWABLE, "preview.png"), *PREVIEW_TIME, pill_box, comet_box)

    xml_path = os.path.join(RAW, "watchface.xml")
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(build_xml(pill_box, comet_box))
    print(f"\nwatchface.xml written to {os.path.relpath(xml_path, HERE)}")


if __name__ == "__main__":
    main()
