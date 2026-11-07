import Testing
@testable import MomoMobileCore

@MainActor
private final class ControlledAuthenticationContext: DeviceAuthenticationContext {
    var available = true
    var invalidations = 0
    var evaluationCount = 0
    private var result: CheckedContinuation<Bool, any Error>?
    private var started: CheckedContinuation<Void, Never>?

    func canAuthenticate() -> Bool { available }

    func authenticate() async throws -> Bool {
        evaluationCount += 1
        return try await withCheckedThrowingContinuation { continuation in
            result = continuation
            started?.resume()
            started = nil
        }
    }

    func waitUntilEvaluating() async {
        if result != nil { return }
        await withCheckedContinuation { started = $0 }
    }

    func succeed(_ value: Bool = true) {
        let continuation = result
        result = nil
        continuation?.resume(returning: value)
    }

    func fail() {
        struct Cancelled: Error {}
        let continuation = result
        result = nil
        continuation?.resume(throwing: Cancelled())
    }

    func invalidate() {
        invalidations += 1
        // Deliberately do not settle the result: an OS callback may already
        // be queued when its context is invalidated.
    }
}

@Suite("Device authentication lifecycle")
@MainActor
struct DeviceAuthenticationControllerTests {
    @Test("Current authentication success unlocks the workspace")
    func currentSuccess() async {
        let context = ControlledAuthenticationContext()
        let controller = DeviceAuthenticationController(makeContext: { context })
        let authentication = Task { await controller.authenticateIfNeeded() }
        await context.waitUntilEvaluating()
        #expect(controller.isAuthenticating)
        #expect(!controller.isUnlocked)
        context.succeed()
        await authentication.value
        #expect(controller.isUnlocked)
        #expect(!controller.isAuthenticating)
        #expect(controller.errorMessage == nil)
    }

    @Test("Locking fences an already queued authentication success")
    func lateSuccessAfterLock() async {
        let context = ControlledAuthenticationContext()
        let controller = DeviceAuthenticationController(makeContext: { context })
        let authentication = Task { await controller.authenticateIfNeeded() }
        await context.waitUntilEvaluating()
        controller.lock()
        context.succeed()
        await authentication.value
        #expect(!controller.isUnlocked)
        #expect(!controller.isAuthenticating)
        #expect(controller.errorMessage == nil)
        #expect(context.invalidations == 1)
    }

    @Test("Duplicate unlock calls share the current attempt")
    func duplicateUnlock() async {
        let context = ControlledAuthenticationContext()
        let controller = DeviceAuthenticationController(makeContext: { context })
        let authentication = Task { await controller.authenticateIfNeeded() }
        await context.waitUntilEvaluating()
        await controller.authenticateIfNeeded()
        #expect(context.evaluationCount == 1)
        context.succeed()
        await authentication.value
    }

    @Test("A device without authentication remains locked")
    func unavailableDeviceAuthentication() async {
        let context = ControlledAuthenticationContext()
        context.available = false
        let controller = DeviceAuthenticationController(makeContext: { context })
        await controller.authenticateIfNeeded()
        #expect(!controller.isUnlocked)
        #expect(!controller.isAuthenticating)
        #expect(controller.errorMessage != nil)
        #expect(context.evaluationCount == 0)
    }

    @Test("Lock retires the current attempt immediately and invalidates it once")
    func lockRetiresAttempt() async {
        let context = ControlledAuthenticationContext()
        let controller = DeviceAuthenticationController(makeContext: { context })
        let authentication = Task { await controller.authenticateIfNeeded() }
        await context.waitUntilEvaluating()
        controller.lock()
        controller.lock()
        #expect(!controller.isAuthenticating)
        #expect(context.invalidations == 1)
        context.fail()
        await authentication.value
        #expect(controller.errorMessage == nil)
        #expect(!controller.isUnlocked)
    }

    @Test("An old success cannot settle a newer pending authentication")
    func newAttemptRetainsOwnership() async {
        let old = ControlledAuthenticationContext()
        let current = ControlledAuthenticationContext()
        var next = 0
        let controller = DeviceAuthenticationController(makeContext: {
            defer { next += 1 }
            return next == 0 ? old : current
        })
        let oldTask = Task { await controller.authenticateIfNeeded() }
        await old.waitUntilEvaluating()
        controller.lock()
        let currentTask = Task { await controller.authenticateIfNeeded() }
        await current.waitUntilEvaluating()
        old.succeed()
        await oldTask.value
        #expect(controller.isAuthenticating)
        #expect(!controller.isUnlocked)
        current.succeed()
        await currentTask.value
        #expect(controller.isUnlocked)
    }

    @Test("An old result cannot replace a newer successful unlock", arguments: [true, false])
    func oldResultAfterNewSuccess(oldSucceeds: Bool) async {
        let old = ControlledAuthenticationContext()
        let current = ControlledAuthenticationContext()
        var next = 0
        let controller = DeviceAuthenticationController(makeContext: {
            defer { next += 1 }
            return next == 0 ? old : current
        })
        let oldTask = Task { await controller.authenticateIfNeeded() }
        await old.waitUntilEvaluating()
        controller.lock()
        let currentTask = Task { await controller.authenticateIfNeeded() }
        await current.waitUntilEvaluating()
        current.succeed()
        await currentTask.value
        if oldSucceeds { old.succeed() } else { old.fail() }
        await oldTask.value
        #expect(controller.isUnlocked)
        #expect(!controller.isAuthenticating)
        #expect(controller.errorMessage == nil)
    }

    @Test("A current failed or declined attempt stays locked", arguments: [true, false])
    func currentFailure(fails: Bool) async {
        let context = ControlledAuthenticationContext()
        let controller = DeviceAuthenticationController(makeContext: { context })
        let authentication = Task { await controller.authenticateIfNeeded() }
        await context.waitUntilEvaluating()
        if fails { context.fail() } else { context.succeed(false) }
        await authentication.value
        #expect(!controller.isUnlocked)
        #expect(!controller.isAuthenticating)
        #expect((controller.errorMessage != nil) == fails)
    }
}
