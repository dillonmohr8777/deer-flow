import Combine
import Foundation
import LocalAuthentication

@MainActor
protocol DeviceAuthenticationContext: AnyObject {
    func canAuthenticate() -> Bool
    func authenticate() async throws -> Bool
    func invalidate()
}

@MainActor
private final class SystemAuthenticationContext: DeviceAuthenticationContext {
    private let context = LAContext()

    init() {
        context.localizedCancelTitle = "Stay Locked"
    }

    func canAuthenticate() -> Bool {
        var error: NSError?
        return context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error)
    }

    func authenticate() async throws -> Bool {
        try await context.evaluatePolicy(
            .deviceOwnerAuthentication,
            localizedReason: "Unlock your private MomoBot workspace"
        )
    }

    func invalidate() {
        context.invalidate()
    }
}

@MainActor
public final class DeviceAuthenticationController: ObservableObject {
    private final class Attempt {
        let context: any DeviceAuthenticationContext

        init(context: any DeviceAuthenticationContext) {
            self.context = context
        }
    }

    private enum State {
        case locked(message: String?)
        case authenticating(Attempt)
        case unlocked
    }

    @Published private var state: State = .locked(message: nil)
    private let makeContext: () -> any DeviceAuthenticationContext

    public var isUnlocked: Bool {
        if case .unlocked = state { return true }
        return false
    }

    public var isAuthenticating: Bool { activeAttempt != nil }

    public var errorMessage: String? {
        if case .locked(let message) = state { return message }
        return nil
    }

    private var activeAttempt: Attempt? {
        if case .authenticating(let attempt) = state { return attempt }
        return nil
    }

    public convenience init() {
        self.init(makeContext: { SystemAuthenticationContext() })
    }

    init(makeContext: @escaping () -> any DeviceAuthenticationContext) {
        self.makeContext = makeContext
    }

    public func authenticateIfNeeded() async {
        guard case .locked = state else { return }
        let context = makeContext()
        guard context.canAuthenticate() else {
            state = .locked(message: "Set a device passcode, Face ID, or Touch ID before using MomoBot.")
            return
        }
        let attempt = Attempt(context: context)
        state = .authenticating(attempt)
        do {
            let unlocked = try await context.authenticate()
            guard activeAttempt === attempt else { return }
            state = unlocked ? .unlocked : .locked(message: nil)
        } catch {
            guard activeAttempt === attempt else { return }
            state = .locked(message: "MomoBot stayed locked. Try again when you're ready.")
        }
    }

    public func lock() {
        let attempt = activeAttempt
        // Retire ownership before invalidating: cancellation may race a
        // success/error already queued by LocalAuthentication.
        state = .locked(message: nil)
        attempt?.context.invalidate()
    }
}
