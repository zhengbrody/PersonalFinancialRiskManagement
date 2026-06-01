import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { SiteShell } from "@/components/site-shell";
import { MarketThemeSync } from "@/components/market-theme-sync";
import { Providers } from "./providers";

/**
 * Pre-hydration theme boot. Runs before first paint (flash-free) and at
 * runtime in the browser — so it's correct even when the HTML is
 * statically generated / CDN-cached. Light during the trading day (04:00–
 * 20:00 ET = 5pm PT); dark for the overnight session (20:00–04:00 ET).
 *
 * This mirrors `isDaySession()` in lib/market-hours.ts — keep in sync.
 */
const THEME_BOOT = `(function(){try{
  var p=new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",hour:"2-digit",minute:"2-digit",hour12:false}).formatToParts(new Date());
  var g=function(t){var f=p.find(function(x){return x.type===t});return f?f.value:""};
  var h=parseInt(g("hour"),10)%24,m=parseInt(g("minute"),10),mins=h*60+m;
  var day=mins>=240&&mins<1200;
  var e=document.documentElement;
  e.classList.toggle("dark",!day);
  e.style.colorScheme=day?"light":"dark";
}catch(_){document.documentElement.classList.add("dark");}})();`;

const geistSans = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist-sans",
  weight: "100 900",
});
const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-geist-mono",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "MindMarket — Portfolio Risk",
  description: "Institutional-grade portfolio risk analytics.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Market-synced theme: the boot script below sets `.dark` from the live
  // ET market session before paint; <MarketThemeSync> flips it at the
  // open/close boundary while the tab stays open. `suppressHydrationWarning`
  // because that script mutates the <html> class before React hydrates.
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
        <MarketThemeSync />
        <Providers>
          <SiteShell>{children}</SiteShell>
        </Providers>
      </body>
    </html>
  );
}
