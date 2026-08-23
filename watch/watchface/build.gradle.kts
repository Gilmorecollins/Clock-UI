plugins {
    id("com.android.application")
}

android {
    namespace = "com.gilmorecollins.radialclock"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.gilmorecollins.radialclock"
        // Wear OS 4 is the floor for any Watch Face Format bundle. The face itself
        // declares format version 5 in the manifest, so it renders fully on Wear OS 6.
        minSdk = 33
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    // No code, no Java/Kotlin sources, no dependencies - just resources.
    buildFeatures {
        buildConfig = false
    }
}
