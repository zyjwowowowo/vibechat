import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VibeChat · 先感受自己，再遇见别人",
  description: "以情绪为入口的 AI 社交与私密回顾空间",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
