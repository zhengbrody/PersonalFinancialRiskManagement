import { redirect } from "next/navigation";

/**
 * The public pricing surface is intentionally retired for the current product
 * phase. Keep the route as a redirect so old bookmarks and search results land
 * on the product story instead of a stale commercial page.
 */
export default function PricingPage() {
  redirect("/product");
}
