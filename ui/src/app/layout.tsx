import type { Metadata } from "next";
import { Source_Sans_3, Source_Serif_4 } from "next/font/google";

import { Shell } from "@/components/shell";

import "./globals.css";

const sans = Source_Sans_3({
  subsets: ["latin", "latin-ext"],
  variable: "--font-source-sans",
});

const serif = Source_Serif_4({
  subsets: ["latin", "latin-ext"],
  variable: "--font-source-serif",
});

export const metadata: Metadata = {
  title: "Ajan Çalıştırıcı",
  description: "Doğal dille tarif edilen ajanları sürümlü AgentSpec olarak zamanında çalıştırır.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="tr">
      <body className={`${sans.variable} ${serif.variable} antialiased`}>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
