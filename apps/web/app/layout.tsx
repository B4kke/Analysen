import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Analysen",
  description: "Kildebevisst norsk OSINT og bakgrunnsanalyse",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="nb">
      <body>{children}</body>
    </html>
  );
}
