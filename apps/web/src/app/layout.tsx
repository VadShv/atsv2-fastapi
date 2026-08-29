import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "ATS Core — подбор персонала",
  description: "AI-native система автоматизации подбора персонала",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>
        {/* Ссылка для пропуска к основному контенту (a11y) */}
        <a href="#main" className="sr-only sr-only-focusable">
          Перейти к основному содержимому
        </a>
        <Providers>
          <div className="min-h-screen">{children}</div>
        </Providers>
      </body>
    </html>
  );
}
