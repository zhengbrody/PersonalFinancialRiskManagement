/**
 * Tiny inline "Learn what this means →" deep-link from a cockpit card to the
 * matching /learn topic. Connects the authenticated risk surfaces to the
 * educational hub (internal linking + in-context learning). Server-safe (no
 * client hooks) so it renders inside SSR and client cards alike.
 */

import Link from "next/link";
import { LEARN_BY_SLUG } from "@/lib/learn-content";

export function LearnHint({
  topic,
  label,
  className,
}: {
  topic: string;
  label?: string;
  className?: string;
}) {
  // Guard against a typo'd slug at build/test time without crashing render.
  if (!LEARN_BY_SLUG[topic]) return null;
  return (
    <Link
      href={`/learn/${topic}`}
      className={`text-xs text-primary hover:underline ${className ?? ""}`}
    >
      {label ?? "Learn what this means"} →
    </Link>
  );
}
