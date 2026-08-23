#!/usr/bin/env python3
"""
Generates the Radial Clock watch face assets and res/raw/watchface.xml.

The web version (../../index.html) draws two dials with 60 CSS elements each and
counter-rotates every label so it stays upright. Watch Face Format has no DOM, so
the same effect is built from:

  * one PNG per dial holding all 60 ticks   -- the ticks rotate WITH the dial,
    so they can be baked into a static image
  * one PartText per label (12 per dial)    -- these must counter-rotate, so they
    stay live elements with their own angle Transform

Everything below is derived from the CSS in ../../style.css, rescaled from the
360px web mockup to the 450x450 canvas Wear OS designs against.

Run:  python watch/tools/generate.py
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

TICK_COLOR = (255, 255, 255, 153)   # CSS #fff9
DIAL_TEXT = "#ffffff"

# Seconds dial (outer).  CSS: --dail-size = radius - 8, font-size 18, weight 800.
SEC_TICK_OUTER = 212
SEC_TICK_MINOR = 10                 # CSS .spike is 8px wide
SEC_TICK_MAJOR = 19                 # CSS adds box-shadow:-7px 0, roughly doubling it
SEC_TICK_WIDTH = 2.5
SEC_NUM_RADIUS = 178
SEC_NUM_SIZE = 25
SEC_IMG = 440                       # tick image is cropped to the annulus it needs

# Minutes dial (inner).  CSS: --dail-size = radius - 65, font-size 16.
MIN_TICK_OUTER = 148
MIN_TICK_MINOR = 9
MIN_TICK_MAJOR = 17
MIN_TICK_WIDTH = 2.2
MIN_NUM_RADIUS = 112
MIN_NUM_SIZE = 23
MIN_IMG = 310

# Centre hour readout.  CSS: font-size 70 on a 360 clock -> 87.5 here.
HOUR_SIZE = 88

# Minute pill on the right rim.  CSS .minute + .minute:after.
PILL_LEFT = 281
PILL_RIGHT = 429                    # open on the right: CSS border-right: none
PILL_HEIGHT = 58
PILL_STROKE = 2.5
PILL_BACKDROP_RIGHT = 341           # CSS .minute has background:#000 behind the digits
MINUTE_SIZE = 46
MINUTE_CX = 312                     # centre of the digits inside the pill

SS = 4                              # supersampling factor for antialiasing

# The CSS puts `transition: 1s linear` on the seconds dial, so on the web it glides
# continuously rather than ticking. SECOND_MILLISECOND reproduces that, and the
# FRAME_RATE_HINT below is what makes it watchable -- without the hint the runtime
# only presents 10fps and the glide reads as stutter.
#
# Set this to "SECOND" for a once-per-second step instead. That is much cheaper
# (~1fps) but it loses the continuous radial motion the whole design is built on.
#
# The minutes dial deliberately stays on plain MINUTE: the CSS only eases it for
# 1s at each minute boundary, so a step is visually equivalent. MINUTE_SECOND
# would wrongly creep it across the whole minute.
SECONDS_SOURCE = "SECOND_MILLISECOND"

# Without this, the runtime presents the face at exactly 10.0fps -- a flat 100ms
# cadence on a 60Hz panel, even though a frame only costs 15-34ms to draw. That
# throttle, not our draw cost, is what made the glide look choppy: deleting all 24
# labels made frames 38% cheaper and did not raise the rate at all.
#
# <Sweep> is the only explicit frame-rate request in the format. It is defined for
# AnalogClock hands rather than Groups, so this adds a completely invisible swept
# second hand purely as a hint -- and the rate it unlocks applies to the whole
# surface, so the dials and labels get it too.
#
# Measured on the Galaxy Watch 4, screen on:
#     no hint          10.0 fps   (flat 100ms cadence)
#     frequency=15     20.2 fps
#     frequency=60     24.6 fps   (p50 gap 33ms, many frames at a single vsync)
#
# 0% janky frames in every case. Set FRAME_RATE_HINT = False to get the stock
# 10fps back, which draws less power.
FRAME_RATE_HINT = True
SWEEP_FREQUENCY = 60

# Ambient alphas. The quality bar (WO-P7) is 15% *mean luminance* across the face,
# not a count of lit pixels -- and this design is nearly all black, so the entire
# interactive face measures only 4.46%. There is no power reason to hide anything.
#
#   ticks @90, labels hidden (the original, over-cautious guess)  1.77%
#   ticks + minute labels @160                                    2.63%   <- used
#   everything including the seconds ring                         4.00%
#
# The seconds dial still goes dark in ambient, for correctness rather than power:
# ambient only refreshes once a minute, so a seconds dial would sit frozen on a
# stale value, which is worse than not showing it. The minutes dial and the
# readouts all tick once a minute, which matches ambient exactly.
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
# fixed set. At +/-2px it is imperceptible in either mode. Children sit within
# 0..450 of the group, and the outermost ticks stop at radius 212 (13px shy of the
# edge), so a 2px shift cannot push anything outside the group's bounds.
BURN_IN_DRIFT = True

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "watchface", "src", "main", "res")
DRAWABLE = os.path.join(RES, "drawable")
RAW = os.path.join(RES, "raw")
FONT_DIR = os.path.join(RES, "font")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def polar(radius: float, degrees: float) -> tuple[float, float]:
    """Canvas coordinates at `radius` from centre, `degrees` clockwise from 3 o'clock.

    Matches the CSS `rotate(Ndeg) translateX(r)` convention, where index 0 sits at
    3 o'clock and the dial advances clockwise.
    """
    rad = math.radians(degrees)
    return CX + radius * math.cos(rad), CY + radius * math.sin(rad)


def draw_dial(path: str, box: int, outer: float, minor: float, major: float, width: float) -> None:
    """Render the 60 ticks of one dial into a square PNG centred on the canvas centre."""
    img = Image.new("RGBA", (box * SS, box * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # The image is centred on the canvas, so shift canvas coords into image coords.
    off = (SIZE - box) / 2

    for i in range(60):
        angle = 6 * i
        length = major if i % 5 == 0 else minor
        x0, y0 = polar(outer - length, angle)
        x1, y1 = polar(outer, angle)
        d.line(
            [((x0 - off) * SS, (y0 - off) * SS), ((x1 - off) * SS, (y1 - off) * SS)],
            fill=TICK_COLOR,
            width=max(1, round(width * SS)),
        )

    img.resize((box, box), Image.LANCZOS).save(path)
    print(f"  {os.path.basename(path)}  {box}x{box}")


def draw_pill(path: str) -> tuple[int, int, int, int]:
    """The minute capsule: rounded on the left, open on the right, opaque behind the digits.

    Returned as a tightly cropped image plus its placement box. The capsule covers
    about 5% of the canvas, and this layer is composited on every frame, so keeping
    it full-screen wasted most of a screen's worth of blending per frame.
    """
    img = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    top = (CY - PILL_HEIGHT / 2) * SS
    bottom = (CY + PILL_HEIGHT / 2) * SS
    left = PILL_LEFT * SS
    right = PILL_RIGHT * SS
    radius = (PILL_HEIGHT / 2) * SS
    stroke = max(1, round(PILL_STROKE * SS))

    # Opaque backdrop so the rotating dials do not show through the digits.
    d.rounded_rectangle(
        [left, top, PILL_BACKDROP_RIGHT * SS, bottom],
        radius=radius,
        fill=(0, 0, 0, 255),
    )

    # Left cap: a half-capsule arc from 90deg round to 270deg.
    d.arc([left, top, left + 2 * radius, bottom], start=90, end=270, fill=(255, 255, 255, 255), width=stroke)
    # Top and bottom rails running out to the rim, with no right-hand cap.
    inset = stroke / 2
    d.line([left + radius, top + inset, right, top + inset], fill=(255, 255, 255, 255), width=stroke)
    d.line([left + radius, bottom - inset, right, bottom - inset], fill=(255, 255, 255, 255), width=stroke)

    full = img.resize((SIZE, SIZE), Image.LANCZOS)
    box = full.getbbox()
    full.crop(box).save(path)
    x0, y0, x1, y1 = box
    print(f"  {os.path.basename(path)}  {x1 - x0}x{y1 - y0} at ({x0},{y0})"
          f"  [was {SIZE}x{SIZE}, {100 * (x1 - x0) * (y1 - y0) // (SIZE * SIZE)}% of canvas]")
    return box


def draw_blank(path: str) -> None:
    """A 2x2 transparent pixel for the invisible frame-rate hint hand to point at."""
    Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(path)
    print(f"  {os.path.basename(path)}  2x2")


def draw_preview(path: str, hour: int, minute: int, second: int,
                 pill_box: tuple[int, int, int, int]) -> None:
    """A static render of the face for the watch face picker."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))

    for name, box in (("ticks_seconds.png", SEC_IMG), ("ticks_minutes.png", MIN_IMG)):
        layer = Image.open(os.path.join(DRAWABLE, name)).convert("RGBA")
        rotated = layer.rotate(6 * (second if "seconds" in name else minute), resample=Image.BICUBIC)
        off = int((SIZE - box) / 2)
        img.alpha_composite(rotated, (off, off))

    d = ImageDraw.Draw(img)

    def font(size: int, bold: bool) -> ImageFont.FreeTypeFont:
        name = "comfortaa_bold.ttf" if bold else "comfortaa_regular.ttf"
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

    def centred(text: str, cx: float, cy: float, f: ImageFont.FreeTypeFont, fill=(255, 255, 255, 255)):
        box = d.textbbox((0, 0), text, font=f)
        d.text((cx - (box[0] + box[2]) / 2, cy - (box[1] + box[3]) / 2), text, font=f, fill=fill)

    # Dial labels, positioned as they land once the dial has rotated.
    for i in range(0, 60, 5):
        sx, sy = polar(SEC_NUM_RADIUS, 6 * (i - second))
        centred(str(i), sx, sy, font(SEC_NUM_SIZE, True))
        mx, my = polar(MIN_NUM_RADIUS, 6 * (i - minute))
        centred(str(i), mx, my, font(MIN_NUM_SIZE, False))

    centred(str(hour), CX, CY, font(HOUR_SIZE, True))

    pill = Image.open(os.path.join(DRAWABLE, "pill.png")).convert("RGBA")
    img.alpha_composite(pill, (pill_box[0], pill_box[1]))
    d = ImageDraw.Draw(img)
    centred(str(minute), MINUTE_CX, CY, font(MINUTE_SIZE, True))

    img.convert("RGB").save(path)
    print(f"  {os.path.basename(path)}  {SIZE}x{SIZE}")


# --------------------------------------------------------------------------
# watchface.xml
# --------------------------------------------------------------------------

def dial_labels(radius: float, size: int, weight: str, source: str, prefix: str,
                box_w: int, box_h: int, indent: str) -> str:
    """One PartText per 5-minute label, each cancelling out its dial's rotation.

    The parent Group rotates by -6*[source]; every label rotates itself back by
    +6*[source] about its own centre, so the digits stay upright while travelling
    around the dial.  This is the CSS `rotate(calc(var(--dRotate) - var(--rotate)))`
    trick, minus the inherited rotation the DOM gave us for free.
    """
    out = []
    for i in range(0, 60, 5):
        x, y = polar(radius, 6 * i)
        out.append(f"""{indent}<PartText name="{prefix}_label_{i}"
{indent}          x="{round(x - box_w / 2)}" y="{round(y - box_h / 2)}"
{indent}          width="{box_w}" height="{box_h}" pivotX="0.5" pivotY="0.5">
{indent}  <Transform target="angle" value="6 * [{source}]" />
{indent}  <Text align="CENTER">
{indent}    <Font family="comfortaa" size="{size}" weight="{weight}" color="{DIAL_TEXT}">{i}</Font>
{indent}  </Text>
{indent}</PartText>""")
    return "\n".join(out)


def build_xml(pill_box: tuple[int, int, int, int]) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!--
  Radial Clock - generated by watch/tools/generate.py, do not hand-edit.
  Edit the constants in that script and re-run it instead.
-->
<WatchFace width="{SIZE}" height="{SIZE}" clipShape="CIRCLE">

  <Metadata key="CLOCK_TYPE" value="DIGITAL" />
  <Metadata key="PREVIEW_TIME" value="12:48:27" />

  <Scene backgroundColor="#000000">
{drift_open()}
    <!-- Outer dial: seconds.  Hidden in ambient - moving parts are not allowed
         there, and this is the single biggest consumer of lit pixels. -->
    <Group name="seconds_dial" x="0" y="0" width="{SIZE}" height="{SIZE}"
           pivotX="0.5" pivotY="0.5">
      <Variant mode="AMBIENT" target="alpha" value="0" />
      <Transform target="angle" value="-6 * [{SECONDS_SOURCE}]" />

      <PartImage name="seconds_ticks"
                 x="{round((SIZE - SEC_IMG) / 2)}" y="{round((SIZE - SEC_IMG) / 2)}"
                 width="{SEC_IMG}" height="{SEC_IMG}">
        <Image resource="ticks_seconds" />
      </PartImage>

{dial_labels(SEC_NUM_RADIUS, SEC_NUM_SIZE, "BOLD", SECONDS_SOURCE, "second", 56, 34, "      ")}
    </Group>

    <!-- Inner dial: minutes.  This whole dial stays visible in ambient: it advances
         once a minute, which is exactly the ambient refresh rate, so it stays
         accurate and keeps the radial design legible on the always-on display. -->
    <Group name="minutes_dial" x="0" y="0" width="{SIZE}" height="{SIZE}"
           pivotX="0.5" pivotY="0.5">
      <Transform target="angle" value="-6 * [MINUTE]" />

      <PartImage name="minutes_ticks"
                 x="{round((SIZE - MIN_IMG) / 2)}" y="{round((SIZE - MIN_IMG) / 2)}"
                 width="{MIN_IMG}" height="{MIN_IMG}">
        <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_DIAL_ALPHA}" />
        <Image resource="ticks_minutes" />
      </PartImage>

      <Group name="minutes_labels" x="0" y="0" width="{SIZE}" height="{SIZE}">
        <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_DIAL_ALPHA}" />

{dial_labels(MIN_NUM_RADIUS, MIN_NUM_SIZE, "NORMAL", "MINUTE", "minute", 48, 30, "        ")}
      </Group>
    </Group>

    <!-- Centre hour readout. The web version hardcodes getHours(), i.e. 24-hour;
         on a watch it is better to follow whatever the wearer has set. -->
    <PartText name="hour" x="0" y="{round(CY - 70)}" width="{SIZE}" height="140">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_TEXT_ALPHA}" />
      <Text align="CENTER">
        <Font family="comfortaa" size="{HOUR_SIZE}" weight="BOLD" color="#ffffff">
          <Template>%d<Parameter expression="[IS_24_HOUR_MODE] ? [HOUR_0_23] : [HOUR_1_12]" /></Template>
        </Font>
      </Text>
    </PartText>

    <!-- Minute capsule on the right rim, drawn over the dials. Cropped to its own
         bounds rather than a full-canvas layer, since this composites every frame. -->
    <PartImage name="pill" x="{pill_box[0]}" y="{pill_box[1]}"
               width="{pill_box[2] - pill_box[0]}" height="{pill_box[3] - pill_box[1]}">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_TEXT_ALPHA}" />
      <Image resource="pill" />
    </PartImage>

    <PartText name="minute" x="{round(MINUTE_CX - 45)}" y="{round(CY - 35)}"
              width="90" height="70">
      <Variant mode="AMBIENT" target="alpha" value="{AMBIENT_TEXT_ALPHA}" />
      <Text align="CENTER">
        <Font family="comfortaa" size="{MINUTE_SIZE}" weight="BOLD" color="#ffffff">
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

    print("assets:")
    draw_dial(os.path.join(DRAWABLE, "ticks_seconds.png"), SEC_IMG,
              SEC_TICK_OUTER, SEC_TICK_MINOR, SEC_TICK_MAJOR, SEC_TICK_WIDTH)
    draw_dial(os.path.join(DRAWABLE, "ticks_minutes.png"), MIN_IMG,
              MIN_TICK_OUTER, MIN_TICK_MINOR, MIN_TICK_MAJOR, MIN_TICK_WIDTH)
    pill_box = draw_pill(os.path.join(DRAWABLE, "pill.png"))
    draw_blank(os.path.join(DRAWABLE, "blank.png"))
    draw_preview(os.path.join(DRAWABLE, "preview.png"), 12, 48, 27, pill_box)

    xml_path = os.path.join(RAW, "watchface.xml")
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(build_xml(pill_box))
    print(f"\nwatchface.xml written to {os.path.relpath(xml_path, HERE)}")


if __name__ == "__main__":
    main()
