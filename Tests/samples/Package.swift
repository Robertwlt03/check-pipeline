// swift-tools-version: 6.0
// Samples with a mistake for every rule, so the checks can test themselves (see check_pipeline/checks/samples.py).
import PackageDescription

let package = Package(
    name: "Samples",
    platforms: [.macOS(.v14)],
    targets: [.executableTarget(name: "Samples", path: "Sources")]
)
