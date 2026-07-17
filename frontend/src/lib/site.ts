import type { Metadata } from "next";

/** The public site origin — single source (was re-declared in many files). */
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

/**
 * Shared metadata builder for public marketing/content pages: canonical +
 * OpenGraph (siteName "MindMarket", the versioned OG card) + Twitter card, from
 * one place so the OG-image version and siteName can't drift across pages.
 */
export function pageMetadata(opts: {
  title: string;
  description: string;
  path: string;
  ogType?: "website" | "article";
}): Metadata {
  const { title, description, path, ogType = "article" } = opts;
  const documentTitle = /\bMindMarket(?: AI)?\b/.test(title)
    ? title
    : `${title} | MindMarket`;
  return {
    // Use an absolute title here so pages whose editorial title already names
    // MindMarket do not receive the root "| MindMarket" template twice.
    title: { absolute: documentTitle },
    description,
    alternates: { canonical: path },
    openGraph: {
      type: ogType,
      title: documentTitle,
      description,
      url: `${SITE_URL}${path}`,
      siteName: "MindMarket",
      images: ["/og.jpg?v=3"],
    },
    twitter: {
      card: "summary_large_image",
      title: documentTitle,
      description,
      images: ["/og.jpg?v=3"],
    },
  };
}
