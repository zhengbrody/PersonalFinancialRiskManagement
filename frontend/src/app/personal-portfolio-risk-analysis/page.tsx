import { SeoLanding, seoMetadata } from "@/components/marketing/seo-landing";
import { SEO_BY_PATH } from "@/lib/seo-content";

export const metadata = seoMetadata("/personal-portfolio-risk-analysis");

export default function Page() {
  return <SeoLanding page={SEO_BY_PATH["/personal-portfolio-risk-analysis"]} />;
}
