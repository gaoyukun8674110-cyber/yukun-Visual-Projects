import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "YOLO 检测控制台",
  description: "Upload media, queue YOLO jobs, and inspect real-time detection logs.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
