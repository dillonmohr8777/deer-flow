import Foundation

public enum NavigationDecision: Equatable, Sendable {
    case allowInApp
    case openExternal
    case reject
}

public struct NavigationPolicy: Sendable {
    public enum ConfigurationError: Error {
        case invalidTrustedOrigin
    }

    private let trustedHost: String
    private let trustedPort: Int

    public init(trustedOriginURL: URL) throws {
        guard trustedOriginURL.scheme?.lowercased() == "https",
              trustedOriginURL.user == nil,
              trustedOriginURL.password == nil,
              let host = trustedOriginURL.host?.lowercased()
        else {
            throw ConfigurationError.invalidTrustedOrigin
        }

        trustedHost = host
        trustedPort = trustedOriginURL.port ?? 443
    }

    public func decision(for url: URL) -> NavigationDecision {
        guard url.user == nil, url.password == nil, let scheme = url.scheme?.lowercased() else {
            return .reject
        }

        switch scheme {
        case "https":
            guard let host = url.host?.lowercased() else { return .reject }
            return host == trustedHost && (url.port ?? 443) == trustedPort
                ? .allowInApp
                : .openExternal
        case "tel", "mailto", "sms":
            return .openExternal
        default:
            return .reject
        }
    }

    public func allowsSubframe(_ url: URL) -> Bool {
        if decision(for: url) == .allowInApp {
            return true
        }
        return url.absoluteString.lowercased() == "about:blank" || url.absoluteString.lowercased() == "about:srcdoc"
    }
}
