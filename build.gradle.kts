plugins {
    // 8.13.x is the AGP line that works with Gradle 9.x, which is what is
    // installed here. Older AGP (8.7 and below) fails against Gradle 9.
    id("com.android.application") version "8.13.2" apply false
}
