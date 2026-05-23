import type { Metadata } from "next";
import "./globals.css";
import { AuthStatus } from "./AuthStatus";
import { ThemeToggle } from "./ThemeToggle";

export const metadata: Metadata = {
  title: "Panopticon",
  description: "Autonomous GitLab operations intelligence"
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
