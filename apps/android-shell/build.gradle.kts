// TunxiangOS Android POS Shell
// 仅做 WebView 壳层 + JS Bridge + 商米 SDK 调用，不写业务逻辑

plugins {
    id("com.android.application") version "8.2.0"
    id("org.jetbrains.kotlin.android") version "1.9.22"
}

android {
    namespace = "com.tunxiang.pos"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.tunxiang.pos"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "3.0.0"

        // Mac mini 地址（可通过构建配置覆盖）
        buildConfigField("String", "MAC_MINI_URL", "\"http://192.168.1.100:8000\"")
        buildConfigField("String", "WEB_APP_URL", "\"file:///android_asset/web-pos/index.html\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.webkit:webkit:1.9.0")

    // 商米 SDK（打印/扫码/秤）
    // implementation("com.sunmi:printerlibrary:1.0.18")
    // implementation("com.sunmi:scanhelper:1.0.4")
}
