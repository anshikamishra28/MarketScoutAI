import "./globals.css";

export const metadata = { title: "MarketScoutAI | Market intelligence", description: "Evidence-backed autonomous market research" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
