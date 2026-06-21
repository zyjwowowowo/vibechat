import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VibeChat · 遇见同频的陌生人",
  description: "AI 驱动的情绪匿名社交",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

