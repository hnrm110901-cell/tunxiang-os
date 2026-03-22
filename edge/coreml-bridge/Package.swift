// swift-tools-version:5.9
// TunxiangOS Core ML Bridge — Swift HTTP Server (port 8100)
// 封装 M4 Neural Engine，暴露 /predict/* 给 Python 调用

import PackageDescription

let package = Package(
    name: "coreml-bridge",
    platforms: [
        .macOS(.v14)
    ],
    dependencies: [
        .package(url: "https://github.com/hummingbird-project/hummingbird.git", from: "2.0.0"),
    ],
    targets: [
        .executableTarget(
            name: "CoreMLBridge",
            dependencies: [
                .product(name: "Hummingbird", package: "hummingbird"),
            ],
            path: "Sources"
        ),
    ]
)
