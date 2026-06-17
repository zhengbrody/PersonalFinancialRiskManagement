/**
 * MindMarket monoline icon set.
 *
 * 24×24, 1.7px stroke, outline, `currentColor` — inline <svg> so Tailwind
 * `text-*` classes tint it.
 *
 *   <Icon name="score-gauge" className="h-5 w-5 text-primary" />
 *
 * Tinting: default currentColor; reserve gold (#D4A017) for stress / alert /
 * copilot accents; use an ink stroke on the teal feature chips.
 */
import { type ReactElement, type SVGProps } from "react";

export type IconName =
  | "score-gauge"
  | "volatility"
  | "factors"
  | "shield"
  | "stress"
  | "trend-up"
  | "copilot"
  | "holdings"
  | "research"
  | "scenarios"
  | "alert";

const PATHS: Record<IconName, ReactElement> = {
  "score-gauge": (
    <>
      <path d="M4 15a8 8 0 0 1 16 0" />
      <path d="M12 15l3.6-4.2" />
      <circle cx="12" cy="15" r="1.3" fill="currentColor" stroke="none" />
    </>
  ),
  volatility: <path d="M3 12h3l2.4-7 4 14 2.4-7H21" />,
  factors: (
    <>
      <path d="M5 20v-5" />
      <path d="M10 20V8" />
      <path d="M15 20v-9" />
      <path d="M20 20v-3" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3l7 2.5v5.6c0 4.6-3.2 7.7-7 9.4-3.8-1.7-7-4.8-7-9.4V5.5z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  stress: <path d="M13 2L4 14h6l-1 8 9-12h-6z" />,
  "trend-up": (
    <>
      <path d="M3 16l5-5 4 4 8-8" />
      <path d="M16 7h5v5" />
    </>
  ),
  copilot: (
    <>
      <path d="M12 3l1.7 4.8 4.8 1.7-4.8 1.7L12 16l-1.7-4.8L5.5 9.5l4.8-1.7z" />
      <path d="M19 14l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />
    </>
  ),
  holdings: (
    <>
      <path d="M12 3l8.5 4.7L12 12.4 3.5 7.7z" />
      <path d="M3.5 12.2l8.5 4.7 8.5-4.7" />
    </>
  ),
  research: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M21 21l-5.6-5.6" />
    </>
  ),
  scenarios: (
    <>
      <path d="M4 7h10" />
      <path d="M18 7h2" />
      <path d="M4 12h3" />
      <path d="M11 12h9" />
      <path d="M4 17h8" />
      <path d="M16 17h4" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="9" cy="12" r="2" />
      <circle cx="14" cy="17" r="2" />
    </>
  ),
  alert: (
    <>
      <path d="M10.3 4 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 0-3.4 0z" />
      <path d="M12 9.5v4" />
      <path d="M12 17h.01" />
    </>
  ),
};

export function Icon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {PATHS[name]}
    </svg>
  );
}
