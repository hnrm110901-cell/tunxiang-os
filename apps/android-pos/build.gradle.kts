// TunxiangOS Android POS — Compose Native
// 5 core screens in Jetpack Compose + Room DB offline + Sunmi SDK

plugins {
    id("com.android.application") version "8.2.0" apply false
    id("org.jetbrains.kotlin.android") version "1.9.22" apply false
    id("com.google.devtools.ksp") version "1.9.22-1.0.17" apply false
}

allprojects {
    repositories {
        google()
        mavenCentral()
        // Sunmi SDK Maven
        // maven { url = uri("https://maven.sunmi.com/nexus/content/groups/public/") }
    }
}
