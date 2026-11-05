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

The face has two static radial scales, a central hour, and a pill-shaped minute
readout. The most recent redesign focuses on fluid motion:

- Outer ticks and outer number labels are static.
- A small cyan (`#30D7FF`) arc and leading dot sweep around the outer edge.
- The cyan indicator is the only continuously transformed visual element.
- An invisible WFF `SecondHand` uses `Sweep frequency="SYNC_TO_DEVICE"` to
  request the smoothest cadence the current device can sustain.
- The seconds indicator hides in ambient mode; static minute information stays
  visible there.

This avoids the prior approach of rotating an entire outer dial and
counter-rotating 12 live text labels every frame, which looked laggy.

## Important files

- `tools/generate.py` is the intended source of truth for geometry and WFF XML.
- `watchface/src/main/res/raw/watchface.xml` is the generated watch face the
  APK actually packages.
- `watchface/src/main/res/drawable/` contains generated tick images and the
  preview.
- `watchface/src/main/AndroidManifest.xml` declares the WFF format version.

The machine did not have `python` or `py` available on `PATH`, so the latest
generator changes were mirrored manually into `watchface.xml`. Before making
future geometry changes, install or configure Python with Pillow, run
`python tools/generate.py`, and confirm the generated XML still matches the
source.

## Current uncommitted changes

At handoff time, the working tree has these modifications:

- `tools/generate.py`
- `watchface/src/main/res/raw/watchface.xml`
- `HANDOFF.md`

The latest debug APK was built successfully on 2026-11-05.

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
2. Visually inspect the cyan arc/dot on the emulator and on a physical watch.
   Tune arc length, stroke thickness, and dot diameter if it feels too bold.
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
- Do not put signing credentials in the repository. The project supports an
  external signing directory through `RADIAL_CLOCK_SIGNING`.
