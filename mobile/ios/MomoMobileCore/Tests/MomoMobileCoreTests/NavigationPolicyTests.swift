import Foundation
import Testing
@testable import MomoMobileCore

private let workspace = URL(string: "https://momobot.example/workspace")!

@Suite("Workspace navigation policy")
struct NavigationPolicyTests {
    private let policy = try! NavigationPolicy(trustedOriginURL: workspace)

    @Test("Allows only the exact HTTPS origin in-app", arguments: [
        "https://momobot.example/workspace",
        "https://momobot.example/workspace/threads?id=1",
        "https://momobot.example:443/api/status",
    ])
    func allowsTrustedOrigin(value: String) {
        #expect(policy.decision(for: URL(string: value)!) == .allowInApp)
    }

    @Test("Opens approved external destinations outside the app", arguments: [
        "https://example.com/help",
        "https://momobot.example:8443/workspace",
        "https://momobot.example.evil.example/workspace",
        "mailto:support@example.com",
        "tel:+14125550123",
        "sms:+14125550123",
    ])
    func opensExternalDestinations(value: String) {
        #expect(policy.decision(for: URL(string: value)!) == .openExternal)
    }

    @Test("Rejects unsafe destinations", arguments: [
        "http://momobot.example/workspace",
        "https:///workspace",
        "https://user@momobot.example/workspace",
        "https://user:password@momobot.example/workspace",
        "javascript:alert(1)",
        "data:text/html,blocked",
        "file:///etc/passwd",
    ])
    func rejectsUnsafeDestinations(value: String) {
        #expect(policy.decision(for: URL(string: value)!) == .reject)
    }

    @Test("Rejects an invalid trusted origin")
    func rejectsInvalidTrustedOrigin() {
        #expect(throws: NavigationPolicy.ConfigurationError.self) {
            try NavigationPolicy(trustedOriginURL: URL(string: "http://example.com")!)
        }
    }
}
