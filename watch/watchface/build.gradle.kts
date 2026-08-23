import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
}

// Release signing. The keystore and its passwords deliberately live OUTSIDE the
// repository, in ~/.radial-clock-signing/, for two reasons: nothing inside the
// project tree can leak them into a commit, and editors watching the workspace
// never see the passwords at all. Override the location with the
// RADIAL_CLOCK_SIGNING env var. See watch/README.md for the keytool command.
//
// Without that file the release build goes unsigned rather than failing, so a
// fresh clone still builds.
val signingDir = System.getenv("RADIAL_CLOCK_SIGNING")
    ?: "${System.getProperty("user.home")}/.radial-clock-signing"
val keystorePropertiesFile = File(signingDir, "keystore.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        FileInputStream(keystorePropertiesFile).use { load(it) }
    }
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

    signingConfigs {
        create("release") {
            if (keystorePropertiesFile.exists()) {
                storeFile = File(signingDir, keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keystorePropertiesFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    // No code, no Java/Kotlin sources, no dependencies - just resources.
    buildFeatures {
        buildConfig = false
    }
}
