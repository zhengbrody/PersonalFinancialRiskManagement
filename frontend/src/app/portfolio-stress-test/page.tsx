import { SeoLanding, seoMetadata } from "@/components/marketing/seo-landing";
import { SEO_BY_PATH } from "@/lib/seo-content";

export const metadata = seoMetadata("/portfolio-stress-test");

export default function Page() {
  return <SeoLanding page={SEO_BY_PATH["/portfolio-stress-test"]} />;
}
