// TunxiangOS Android POS Shell - App Module
// 仅做 WebView 壳层 + JS Bridge + 商米 SDK 调用，不写业务逻辑

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
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

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Mac mini 地址（可通过构建配置覆盖）
        buildConfigField("String", "MAC_MINI_URL", "\"http://192.168.1.100:8000\"")
        buildConfigField("String", "COREML_BRIDGE_URL", "\"http://192.168.1.100:8100\"")
        buildConfigField("String", "WEB_APP_URL", "\"file:///android_asset/web-pos/index.html\"")
    }

    // ── 签名配置 ──
    signingConfigs {
        // debug 使用默认 keystore
        getByName("debug") {
            // 使用 Android SDK 默认 debug keystore
        }

        create("release") {
            // 生产签名配置 — 通过环境变量或 local.properties 注入
            // storeFile = file(System.getenv("TXOS_KEYSTORE_PATH") ?: "keystore/release.jks")
            // storePassword = System.getenv("TXOS_KEYSTORE_PASSWORD") ?: ""
            // keyAlias = System.getenv("TXOS_KEY_ALIAS") ?: "tunxiang-pos"
            // keyPassword = System.getenv("TXOS_KEY_PASSWORD") ?: ""
            //
            // 首次生成 keystore:
            //   keytool -genkeypair -v -keystore keystore/release.jks \
            //     -keyalg RSA -keysize 2048 -validity 10000 \
            //     -alias tunxiang-pos \
            //     -dname "CN=TunxiangOS, OU=Mobile, O=Tunxiang Tech, L=Changsha, ST=Hunan, C=CN"
        }
    }

    // ── 构建类型 ──
    buildTypes {
        debug {
            isDebuggable = true
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"

            // Debug 环境使用本地开发 Web App
            buildConfigField("String", "WEB_APP_URL", "\"http://10.0.2.2:5173\"")
        }

        release {
            isDebuggable = false
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )

            // release 签名配置（取消注释以启用）
            // signingConfig = signingConfigs.getByName("release")
        }
    }

    // ── 产品风味（可选：按客户定制） ──
    flavorDimensions += "client"
    productFlavors {
        create("generic") {
            dimension = "client"
            // 通用版本
        }
        create("sunmi") {
            dimension = "client"
            // 商米设备定制（启用商米 SDK）
            buildConfigField("Boolean", "SUNMI_SDK_ENABLED", "true")
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
        viewBinding = true
    }

    // 打包配置
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    // AndroidX
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.webkit:webkit:1.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")

    // WebView 增强
    implementation("androidx.webkit:webkit:1.9.0")

    // 网络（与 Mac mini 通信）
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // JSON
    implementation("com.google.code.gson:gson:2.10.1")

    // 商米 SDK（打印/扫码/秤）
    // implementation("com.sunmi:printerlibrary:1.0.18")
    // implementation("com.sunmi:scanhelper:1.0.4")

    // 测试
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
    androidTestImplementation("androidx.test.espresso:espresso-web:3.5.1")
}
