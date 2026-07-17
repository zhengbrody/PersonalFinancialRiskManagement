import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Product",
  alternates: { canonical: "/product" },
  robots: { index: false, follow: false },
};

export default function RetiredPricingLayout({ children }: { children: React.ReactNode }) {
  return children;
}
