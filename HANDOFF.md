# Clock-UI handoff

## Project

This is a resource-only Wear OS watch face built with Watch Face Format (WFF),
not a conventional Android app. The main module is `watchface/` and the package
name is `com.gilmorecollins.radialclock`.

- WFF format version: `1`
- Minimum Wear OS: Wear OS 4 / API 33
- Target device intent: Galaxy Watch 4, while retaining standard WFF
  compatibility
- Build output: `watchface/build/outputs/apk/debug/watchface-debug.apk`

## Current design

The face matches `design/mockups/radial-clock-comet-concept.png` (verified on
the emulator on 2026-11-05). Geometry was measured from the mockup and scaled to
the 450px canvas; the constants at the top of `tools/generate.py` record it.

- Outer ring: static white ticks (longer and thicker every 5s) and static
  labels 0-55, with 0 at 12 o'clock.
- Inner ring: static grey ticks, no labels.
- Centre: hour right-aligned against a filled `#242728` minute pill.
- Seconds comet: cyan `#0BE1FD` dot, stem and fading tail, one small cropped
  PNG in a rotating Group. It is the only moving element.
- Font: Google Sans Flex Bold (SIL OFL 1.1). Comfortaa was removed.
- An invisible WFF `SecondHand` uses `Sweep frequency="SYNC_TO_DEVICE"` to
  request the smoothest cadence the current device can sustain.
- Ambient keeps the inner ring, hour and minute pill; the comet and outer ring
  hide.

This avoids the prior approach of rotating an entire outer dial and
counter-rotating 12 live text labels every frame, which looked laggy.

## Important files

- `tools/generate.py` is the intended source of truth for geometry and WFF XML.
- `watchface/src/main/res/raw/watchface.xml` is the generated watch face the
  APK actually packages.
- `watchface/src/main/res/drawable/` contains generated tick images and the
  preview.
- `watchface/src/main/AndroidManifest.xml` declares the WFF format version.

Python 3.13 with Pillow is installed on this machine and on the user `PATH`.
Always change the design in `generate.py` and rerun `python tools/generate.py`;
never hand-edit the generated XML or drawables. (Terminals opened before the
install may still see only the Microsoft Store `python` stub; open a new one.)

## Build and deploy

From the repository root:

```powershell
.\gradlew.bat --no-daemon :watchface:assembleDebug
```

The Android SDK is installed under:

```text
C:\Users\colli\AppData\Local\Android\Sdk
```

To install to a specific connected Wear OS emulator:

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb -s emulator-5554 install -r .\watchface\build\outputs\apk\debug\watchface-debug.apk
& $adb -s emulator-5554 shell am broadcast `
  -a com.google.android.wearable.app.DEBUG_SURFACE `
  --es operation set-watchface `
  --es watchFaceId com.gilmorecollins.radialclock
```

Successful selection returns a broadcast result similar to:

```text
result=1, data="Favorite Id=[9] Runtime=[2]"
```

## Test device

An AVD has been created locally:

```text
Galaxy_Watch_4_Wear_OS_4
Wear OS 4 / Android 13 / x86_64
Hardware profile: wearos_small_round
```

Launch it with:

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" `
  -avd Galaxy_Watch_4_Wear_OS_4
```

The emulator was used to build, install, and select the face successfully. It
is not a Samsung-specific emulator, so final animation quality should also be
checked on a real Galaxy Watch 4.

## Known caveats and next steps

1. `SYNC_TO_DEVICE` asks WFF for the fastest smooth rate a device allows; it
   does not guarantee 60 fps. Actual cadence is device-dependent.
2. Check the comet on a physical Galaxy Watch 4, and measure frame rate and
   battery with SYNC_TO_DEVICE as was done for the old design (README Notes).
   Tune `COMET_*` constants if it feels too bold.
3. Use Android Studio's WFF validation and memory-footprint tooling before any
   release build.
4. Consider a user-selectable color theme or a battery-friendly stepped-seconds
   option only after the main animation is approved.
5. There is a non-fatal SDK XML compatibility warning during Gradle builds;
   Android Studio and command-line SDK tools are at different release levels.

## Do not do

- Do not switch this to a legacy custom Kotlin/Canvas watch face renderer. WFF
  is the required long-term Wear OS format.
- Do not reintroduce the full rotating outer bitmap plus counter-rotating live
  labels; that was the main perceived-lag source.
- Do not install to the first `adb` device blindly: a Galaxy A17 phone
  (SM-A175F) is often connected over wireless debugging. Pass `-s` with the
  watch's or emulator's serial.
- Do not put signing credentials in the repository. The project supports an
  external signing directory through `RADIAL_CLOCK_SIGNING`.
