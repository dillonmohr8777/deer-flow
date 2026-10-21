import Foundation
import MomoMobileCore
import SwiftUI
import UIKit
import WebKit

@MainActor
final class BrowserModel: ObservableObject {
    static let workspaceURL: URL = {
        guard let value = Bundle.main.object(forInfoDictionaryKey: "MomoBotWorkspaceURL") as? String,
              let url = URL(string: value),
              (try? NavigationPolicy(trustedOriginURL: url)) != nil
        else {
            fatalError("MomoBotWorkspaceURL must be a valid HTTPS URL")
        }
        return url
    }()

    @Published fileprivate(set) var canGoBack = false
    @Published fileprivate(set) var canGoForward = false
    @Published fileprivate(set) var currentURL: URL?
    @Published fileprivate(set) var errorMessage: String?
    @Published fileprivate(set) var isLoading = true

    fileprivate weak var webView: WKWebView?

    func goBack() { webView?.goBack() }
    func goForward() { webView?.goForward() }
    func reload() { webView?.reloadFromOrigin() }

    func retry() {
        errorMessage = nil
        if webView?.url == nil {
            webView?.load(URLRequest(url: Self.workspaceURL))
        } else {
            reload()
        }
    }

    fileprivate func synchronize(with webView: WKWebView) {
        canGoBack = webView.canGoBack
        canGoForward = webView.canGoForward
        currentURL = webView.url
        isLoading = webView.isLoading
    }
}

struct WorkspaceWebView: UIViewRepresentable {
    @ObservedObject var model: BrowserModel

    func makeCoordinator() -> Coordinator {
        Coordinator(model: model)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .automatic
        model.webView = webView
        webView.load(URLRequest(url: BrowserModel.workspaceURL))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        model.webView = webView
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate {
        private let model: BrowserModel
        private let policy = try! NavigationPolicy(trustedOriginURL: BrowserModel.workspaceURL)

        init(model: BrowserModel) {
            self.model = model
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }

            if navigationAction.targetFrame?.isMainFrame == false {
                decisionHandler(policy.allowsSubframe(url) ? .allow : .cancel)
                return
            }

            guard policy.allowsTopLevelNavigation(
                fromMainFrame: navigationAction.sourceFrame.isMainFrame
            ) else {
                decisionHandler(.cancel)
                return
            }

            switch policy.decision(for: url) {
            case .allowInApp:
                if navigationAction.targetFrame == nil {
                    decisionHandler(.cancel)
                    webView.load(navigationAction.request)
                } else {
                    decisionHandler(.allow)
                }
            case .openExternal:
                decisionHandler(.cancel)
                UIApplication.shared.open(url)
            case .reject:
                decisionHandler(.cancel)
                model.isLoading = false
                model.errorMessage = "MomoBot blocked an unsafe link."
            }
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            model.errorMessage = nil
            model.synchronize(with: webView)
        }

        func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
            model.synchronize(with: webView)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            model.errorMessage = nil
            model.synchronize(with: webView)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            fail(webView, error: error)
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            fail(webView, error: error)
        }

        private func fail(_ webView: WKWebView, error: Error) {
            model.synchronize(with: webView)
            guard (error as NSError).code != NSURLErrorCancelled else { return }
            model.isLoading = false
            model.errorMessage = "Check your internet connection, then try again."
        }
    }
}
