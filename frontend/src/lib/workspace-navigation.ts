/** One primary-navigation model for desktop and mobile. */
export const WORKSPACE_LINKS = [
  { href: "/", label: "Today", icon: "today" },
  { href: "/portfolios", label: "Holdings", icon: "holdings" },
  { href: "/analyze", label: "Analyze", icon: "analyze" },
  { href: "/research", label: "Research", icon: "research" },
  { href: "/copilot", label: "Copilot", icon: "copilot" },
] as const;

export function isWorkspaceRoute(pathname: string, href: string): boolean {
  if (href === "/research") {
    return ["/research", "/markets", "/institutions"].some(
      (route) => pathname === route || pathname.startsWith(`${route}/`),
    );
  }
  if (
    href === "/analyze" &&
    ["/score", "/risk", "/scenarios"].includes(pathname)
  )
    return true;
  return pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
}
