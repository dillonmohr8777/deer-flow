import SwiftUI

struct WorkspaceView: View {
    @StateObject private var browser = BrowserModel()

    var body: some View {
        ZStack {
            WorkspaceWebView(model: browser)
                .accessibilityHidden(browser.errorMessage != nil)
                .allowsHitTesting(browser.errorMessage == nil)

            if let errorMessage = browser.errorMessage {
                FailureView(message: errorMessage, retry: browser.retry)
            }
        }
        .overlay(alignment: .top) {
            if browser.isLoading {
                ProgressView()
                    .controlSize(.small)
                    .padding(8)
                    .background(Color(uiColor: .secondarySystemBackground))
                    .clipShape(Circle())
                    .accessibilityLabel("Loading workspace")
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            BrowserToolbar(browser: browser)
        }
    }
}

private struct BrowserToolbar: View {
    @ObservedObject var browser: BrowserModel

    var body: some View {
        VStack(spacing: 0) {
            Divider()
            HStack(spacing: 8) {
                control("chevron.backward", label: "Back", enabled: browser.canGoBack, action: browser.goBack)
                control("chevron.forward", label: "Forward", enabled: browser.canGoForward, action: browser.goForward)

                Spacer(minLength: 8)

                control("arrow.clockwise", label: "Reload", action: browser.reload)

                ShareLink(item: browser.currentURL ?? BrowserModel.workspaceURL) {
                    Image(systemName: "square.and.arrow.up")
                        .frame(minWidth: 44, minHeight: 44)
                        .contentShape(Rectangle())
                }
                .accessibilityLabel("Share current page")
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 4)
        }
        .background(Color(uiColor: .secondarySystemBackground))
    }

    private func control(
        _ systemImage: String,
        label: String,
        enabled: Bool = true,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .frame(minWidth: 44, minHeight: 44)
                .contentShape(Rectangle())
        }
        .disabled(!enabled)
        .accessibilityLabel(label)
    }
}

private struct FailureView: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "wifi.exclamationmark")
                .font(.largeTitle)
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            Text("Workspace unavailable")
                .font(.title2.bold())
            Text(message)
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button("Try Again", action: retry)
                .buttonStyle(.borderedProminent)
                .frame(minHeight: 44)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(uiColor: .systemBackground))
    }
}
