import LocalAuthentication
import SwiftUI

@main
struct MomoBotApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var authentication = DeviceAuthenticationController()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(authentication)
                .task { await authentication.authenticateIfNeeded() }
                .onChange(of: scenePhase) { _, phase in
                    switch phase {
                    case .active:
                        Task { await authentication.authenticateIfNeeded() }
                    case .background:
                        authentication.lock()
                    default:
                        break
                    }
                }
        }
    }
}

private struct RootView: View {
    @EnvironmentObject private var authentication: DeviceAuthenticationController
    @State private var hasLoadedWorkspace = false

    var body: some View {
        ZStack {
            if hasLoadedWorkspace {
                WorkspaceView()
                    .privacySensitive()
                    .allowsHitTesting(authentication.isUnlocked)
                    .accessibilityHidden(!authentication.isUnlocked)
            }

            if !authentication.isUnlocked {
                LockView()
            }
        }
        .onChange(of: authentication.isUnlocked) { _, isUnlocked in
            if isUnlocked { hasLoadedWorkspace = true }
        }
    }
}

private struct LockView: View {
    @EnvironmentObject private var authentication: DeviceAuthenticationController

    var body: some View {
        VStack(spacing: 24) {
            Image("MomoMark")
                .resizable()
                .scaledToFit()
                .frame(width: 96, height: 96)
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                .accessibilityHidden(true)

            VStack(spacing: 8) {
                Text("MomoBot")
                    .font(.largeTitle.bold())
                Text("Unlock to open your private workspace.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            if let message = authentication.errorMessage {
                Text(message)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            Button {
                Task { await authentication.authenticateIfNeeded() }
            } label: {
                Label("Unlock MomoBot", systemImage: "lock.open.fill")
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            .disabled(authentication.isAuthenticating)
            .accessibilityHint("Uses Face ID, Touch ID, or the device passcode")

            if authentication.isAuthenticating {
                ProgressView("Authenticating")
                    .font(.callout)
            }
        }
        .padding(24)
        .frame(maxWidth: 440)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(uiColor: .systemBackground))
    }
}

@MainActor
private final class DeviceAuthenticationController: ObservableObject {
    @Published private(set) var isUnlocked = false
    @Published private(set) var isAuthenticating = false
    @Published private(set) var errorMessage: String?

    func authenticateIfNeeded() async {
        guard !isUnlocked, !isAuthenticating else { return }

        let context = LAContext()
        context.localizedCancelTitle = "Stay Locked"
        var evaluationError: NSError?

        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &evaluationError) else {
            isUnlocked = false
            errorMessage = "Set a device passcode, Face ID, or Touch ID before using MomoBot."
            return
        }

        isAuthenticating = true
        defer { isAuthenticating = false }

        do {
            isUnlocked = try await context.evaluatePolicy(
                .deviceOwnerAuthentication,
                localizedReason: "Unlock your private MomoBot workspace"
            )
            errorMessage = nil
        } catch {
            isUnlocked = false
            errorMessage = "MomoBot stayed locked. Try again when you're ready."
        }
    }

    func lock() {
        isUnlocked = false
        errorMessage = nil
    }
}
