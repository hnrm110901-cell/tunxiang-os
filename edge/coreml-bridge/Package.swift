// swift-tools-version:5.9
// TunxiangOS Core ML Bridge — Swift HTTP Server (port 8100)
// 封装 M4 Neural Engine，暴露 /predict/* 给 Python 调用

import PackageDescription

let package = Package(
    name: "CoreMLBridge",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/vapor/vapor.git", from: "4.89.0"),
    ],
    targets: [
        .executableTarget(
            name: "CoreMLBridge",
            dependencies: [.product(name: "Vapor", package: "vapor")],
            path: "Sources/CoreMLBridge"
        ),
    ]
)
