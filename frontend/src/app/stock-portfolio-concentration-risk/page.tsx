import { SeoLanding, seoMetadata } from "@/components/marketing/seo-landing";
import { SEO_BY_PATH } from "@/lib/seo-content";

export const metadata = seoMetadata("/stock-portfolio-concentration-risk");

export default function Page() {
  return <SeoLanding page={SEO_BY_PATH["/stock-portfolio-concentration-risk"]} />;
}
