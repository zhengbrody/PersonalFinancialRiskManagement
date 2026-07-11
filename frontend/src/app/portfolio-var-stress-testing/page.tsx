import { SeoLanding, seoMetadata } from "@/components/marketing/seo-landing";
import { SEO_BY_PATH } from "@/lib/seo-content";

export const metadata = seoMetadata("/portfolio-var-stress-testing");

export default function Page() {
  return <SeoLanding page={SEO_BY_PATH["/portfolio-var-stress-testing"]} />;
}
