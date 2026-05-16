import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

