import type { Metadata } from "next";
import localFont from "next/font/local";
import { Instrument_Serif } from "next/font/google";
import "./globals.css";
import { SiteShell } from "@/components/site-shell";
import { MarketThemeSync } from "@/components/market-theme-sync";
import { DAY_START_MINUTES, DAY_END_MINUTES } from "@/lib/market-hours";
import { Providers } from "./providers";

/**
 * Pre-hydration theme boot. Runs before first paint (flash-free) and at
 * runtime in the browser — so it's correct even when the HTML is
 * statically generated / CDN-cached. Light during the trading day (04:00–
 * 20:00 ET = 5pm PT); dark for the overnight session (20:00–04:00 ET).
 *
 * The 04:00/20:00 window is interpolated from `isDaySession`'s constants in
 * lib/market-hours.ts (single source) — the pre-hydration script can't import
 * the module, so we bake the numbers in at build instead of duplicating them.
 */
const THEME_BOOT = `(function(){try{
  var p=new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",hour:"2-digit",minute:"2-digit",hour12:false}).formatToParts(new Date());
  var g=function(t){var f=p.find(function(x){return x.type===t});return f?f.value:""};
  var h=parseInt(g("hour"),10)%24,m=parseInt(g("minute"),10),mins=h*60+m;
  var day=mins>=${DAY_START_MINUTES}&&mins<${DAY_END_MINUTES};
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
// Display serif for marketing headlines only (the "Citadel" editorial look).
// Geist stays the UI/body font.
const instrumentSerif = Instrument_Serif({
  weight: "400",
  style: ["normal", "italic"],
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  applicationName: "MindMarket",
  title: {
    default: "MindMarket | AI Portfolio Risk Analytics",
    template: "%s | MindMarket",
  },
  description:
    "AI portfolio risk analytics for individual investors: portfolio health score, VaR, CVaR, stress tests, factor exposure, and live US rates data.",
  keywords: [
    "MindMarket",
    "portfolio risk analytics",
    "AI portfolio risk management",
    "portfolio health score",
    "VaR calculator",
    "CVaR",
    "stress testing portfolio",
    "factor exposure",
    "US Treasury yield curve",
    "FRED macro data",
  ],
  alternates: {
    canonical: "/",
  },
  // Site-wide Google Search Console HTML-tag verification (was only on the
  // Caddy-served /about.html, so the homepage URL couldn't be verified). Now
  // every Next page — including "/" — carries it. DNS verification (Cloudflare)
  // is the recommended primary method; this is the backup.
  verification: {
    google: "cpW5HG50AaWNMEfTxdGBF6JxeviA-0QFaHDYS0xw_N8",
  },
  openGraph: {
    type: "website",
    url: "/",
    siteName: "MindMarket",
    title: "MindMarket | AI Portfolio Risk Analytics",
    description:
      "Score your portfolio, inspect downside risk, and understand macro exposure with deterministic risk math plus AI explanations.",
    images: [
      {
        url: "/og.jpg",
        width: 1200,
        height: 630,
        alt: "MindMarket AI — know your portfolio's risk before the market tests it",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "MindMarket | AI Portfolio Risk Analytics",
    description:
      "Portfolio health score, VaR/CVaR, stress tests, factor exposure, and live US rates data for individual investors.",
    images: ["/og.jpg"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-snippet": -1,
      "max-image-preview": "large",
      "max-video-preview": -1,
    },
  },
  manifest: "/site.webmanifest",
};

// Structured data for search engines. Static + deterministic (no user data),
// so it lives in the server-rendered root layout and ships with every page.
const JSON_LD = JSON.stringify({
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": `${SITE_URL}/#org`,
      name: "MindMarket AI",
      url: SITE_URL,
      logo: `${SITE_URL}/icons/icon-512.png`,
    },
    {
      "@type": "SoftwareApplication",
      name: "MindMarket AI",
      url: SITE_URL,
      applicationCategory: "FinanceApplication",
      operatingSystem: "Web",
      description:
        "AI portfolio risk analytics for individual investors: portfolio health score (0-1000), VaR/CVaR, stress tests, factor exposure, and an AI copilot grounded in deterministic risk math.",
      // Free educational beta — no paid tiers advertised. (Priced offers
      // return when monetization launches; gate alongside the billing flag.)
      offers: [{ "@type": "Offer", price: "0", priceCurrency: "USD" }],
      publisher: { "@id": `${SITE_URL}/#org` },
    },
  ],
});

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
      <body className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable}`}>
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON_LD }} />
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
        <MarketThemeSync />
        <Providers>
          <SiteShell>{children}</SiteShell>
        </Providers>
      </body>
    </html>
  );
}
