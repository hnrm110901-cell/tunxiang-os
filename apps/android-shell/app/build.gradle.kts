// TunxiangOS Android POS Shell — App Module
// WebView 壳层 + JS Bridge (TXBridge) + Room 离线数据层 + WorkManager 后台同步
// 业务逻辑全部在 React Web App 中

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
}

android {
    namespace = "com.tunxiang.pos"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.tunxiang.pos"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "3.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Mac mini 地址（门店局域网）
        buildConfigField("String", "MAC_MINI_URL", "\"http://192.168.1.100:8000\"")
        buildConfigField("String", "COREML_BRIDGE_URL", "\"http://192.168.1.100:8100\"")
        // 云端 API 地址（用于离线同步引擎）
        buildConfigField("String", "TX_CORE_BASE_URL", "\"https://api.tunxiang.com\"")
        // React Web App 入口（assets 内嵌或远程）
        buildConfigField("String", "WEB_APP_URL", "\"file:///android_asset/web-pos/index.html\"")

        // Room schema 导出目录
        ksp {
            arg("room.schemaLocation", "$projectDir/schemas")
        }
    }

    // ── 签名配置 ──
    signingConfigs {
        getByName("debug") {}
        create("release") {
            // storeFile = file(System.getenv("TXOS_KEYSTORE_PATH") ?: "keystore/release.jks")
            // storePassword = System.getenv("TXOS_KEYSTORE_PASSWORD") ?: ""
            // keyAlias = System.getenv("TXOS_KEY_ALIAS") ?: "tunxiang-pos"
            // keyPassword = System.getenv("TXOS_KEY_PASSWORD") ?: ""
        }
    }

    // ── 构建类型 ──
    buildTypes {
        debug {
            isDebuggable = true
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            buildConfigField("String", "WEB_APP_URL", "\"http://10.0.2.2:5173\"")
            buildConfigField("String", "TX_CORE_BASE_URL", "\"http://10.0.2.2:8000\"")
        }

        release {
            isDebuggable = false
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            // signingConfig = signingConfigs.getByName("release")
        }
    }

    // ── 产品风味 ──
    flavorDimensions += "client"
    productFlavors {
        create("generic") { dimension = "client" }
        create("sunmi") {
            dimension = "client"
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

    // Room 离线数据层
    val roomVersion = "2.6.1"
    implementation("androidx.room:room-runtime:$roomVersion")
    implementation("androidx.room:room-ktx:$roomVersion")
    ksp("androidx.room:room-compiler:$roomVersion")

    // WorkManager 后台同步
    implementation("androidx.work:work-runtime-ktx:2.9.0")

    // 网络（云端 API + Mac mini 通信）
    implementation("com.squareup.retrofit2:retrofit:2.9.0")
    implementation("com.squareup.retrofit2:converter-gson:2.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    // JSON
    implementation("com.google.code.gson:gson:2.10.1")

    // 协程
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // 商米 SDK（按风味启用）
    // sunmiImplementation("com.sunmi:printerlibrary:1.0.18")
    // sunmiImplementation("com.sunmi:scanhelper:1.0.4")

    // 测试
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
    androidTestImplementation("androidx.test.espresso:espresso-web:3.5.1")
}
