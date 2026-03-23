// TunxiangOS Android POS Shell — 项目级 build.gradle.kts
// 仅做 WebView 壳层 + JS Bridge + 商米 SDK 调用，不写业务逻辑

plugins {
    id("com.android.application") version "8.2.0" apply false
    id("org.jetbrains.kotlin.android") version "1.9.22" apply false
}

// 所有子项目通用配置
allprojects {
    repositories {
        google()
        mavenCentral()
        // 商米 SDK Maven 仓库（按需启用）
        // maven { url = uri("https://maven.sunmi.com/nexus/content/groups/public/") }
    }
}
