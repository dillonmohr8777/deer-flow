import "@/styles/globals.css";

import { type Metadata, type Viewport } from "next";

import { PwaBoundary } from "@/components/pwa/pwa-boundary";
import { ThemeProvider } from "@/components/theme-provider";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";

export const metadata: Metadata = {
  title: "MomoBot by Momentum",
  description: "A private workspace where a team of agents takes on real work.",
  manifest: "/manifest.webmanifest",
  applicationName: "MomoBot",
  appleWebApp: {
    capable: true,
    title: "MomoBot",
    statusBarStyle: "default",
  },
  formatDetection: { telephone: false },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [
      {
        url: "/icons/apple-touch-icon.png",
        sizes: "180x180",
        type: "image/png",
      },
    ],
  },
};

// Existing mobile safe-area padding owns the notch and home indicator.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#1b4b9e",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang={DEFAULT_LOCALE}
      suppressContentEditableWarning
      suppressHydrationWarning
    >
      <body>
        <ThemeProvider attribute="class" enableSystem disableTransitionOnChange>
          {children}
          <PwaBoundary />
        </ThemeProvider>
      </body>
    </html>
  );
}
