import type { Metadata } from "next";
import "./globals.css";
import { AuthStatus } from "./AuthStatus";
import { ThemeToggle } from "./ThemeToggle";

export const metadata: Metadata = {
  title: "Panopticon | GitLab Operations Intelligence",
  description: "Agentic GitLab risk, pipeline, incident, Slack, and code-change operations console.",
  icons: {
    icon: "/panopticon-logo.png",
    apple: "/panopticon-logo.png"
  }
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <AuthStatus />
        <ThemeToggle />
        {children}
      </body>
    </html>
  );
}
