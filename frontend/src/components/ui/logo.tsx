/**
 * MindMarket logo — the "M + rising line" mark, drawn inline so it scales
 * crisply and needs no asset file.
 *
 *   <Logo />                        // mark only, 28px
 *   <Logo size={22} withWordmark /> // horizontal lockup (header)
 *
 * Colors are the brand literals (ink bg, white M, gold line). The wordmark
 * inherits currentColor so it adapts to dark/light surfaces.
 */
type LogoProps = {
  size?: number;
  withWordmark?: boolean;
  className?: string;
};

export function Logo({ size = 28, withWordmark = false, className }: LogoProps) {
  const mark = (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="MindMarket"
      style={{ flex: "none" }}
    >
      <rect width="64" height="64" rx="16" fill="#0B0E11" />
      <rect
        x="0.75"
        y="0.75"
        width="62.5"
        height="62.5"
        rx="15.25"
        fill="none"
        stroke="#223039"
        strokeWidth="1.5"
      />
      <circle cx="32" cy="28" r="20" fill="#0B7285" opacity="0.16" />
      <path
        d="M14 46 V20 L32 38 L50 20 V46"
        fill="none"
        stroke="#F8FAFC"
        strokeWidth="4.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M13 50 L31 42 L50 30"
        fill="none"
        stroke="#D4A017"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="50" cy="30" r="3.1" fill="#D4A017" />
    </svg>
  );

  if (!withWordmark) return <span className={className}>{mark}</span>;

  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 10,
        fontWeight: 600,
        letterSpacing: "-0.02em",
        fontSize: size * 0.62,
      }}
    >
      {mark}
      <span>MindMarket</span>
    </span>
  );
}
