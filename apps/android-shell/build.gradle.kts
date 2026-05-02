// TunxiangOS Android POS Shell — 项目级 build.gradle.kts
// 仅做 WebView 壳层 + JS Bridge + 商米 SDK 调用 + 离线数据层
// Compose UI 已移除（统一走 React Web App）

plugins {
    id("com.android.application") version "8.2.0" apply false
    id("org.jetbrains.kotlin.android") version "1.9.22" apply false
    id("com.google.devtools.ksp") version "1.9.22-1.0.17" apply false
}

allprojects {
    repositories {
        google()
        mavenCentral()
        // maven { url = uri("https://maven.sunmi.com/nexus/content/groups/public/") }
    }
}
