import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentRadar — Mission Control",
  description: "Dependency break detection, graph-guided, sandbox-proven.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
