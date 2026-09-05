import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgenticAvatar",
  description: "Real-time AI avatar powered by Salesforce Agentforce",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
