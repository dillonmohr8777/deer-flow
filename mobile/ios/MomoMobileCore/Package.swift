// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "MomoMobileCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "MomoMobileCore", targets: ["MomoMobileCore"]),
    ],
    targets: [
        .target(name: "MomoMobileCore"),
        .testTarget(name: "MomoMobileCoreTests", dependencies: ["MomoMobileCore"]),
    ]
)
