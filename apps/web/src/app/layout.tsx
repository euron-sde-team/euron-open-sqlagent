import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

import type { Metadata, Viewport } from "next";

import { Providers } from "@/lib/providers";

export const metadata: Metadata = {
  title: { default: "SQLAgent", template: "%s | SQLAgent" },
  description: "Ask your databases questions in plain English: one validated, read-only SQL query, run on a read-only connection, shown as a table or a chart.",
  icons: { icon: "/icon.svg" },
};

export const viewport: Viewport = {
  // Meta tags cannot read CSS variables: these mirror --background in globals.css.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f7f7" },
    { media: "(prefers-color-scheme: dark)", color: "#090e10" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
