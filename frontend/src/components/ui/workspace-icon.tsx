/** Small, consistent interface icons. Decorative: the adjacent label names the action. */
export type WorkspaceIconName =
  | "today"
  | "holdings"
  | "analyze"
  | "research"
  | "copilot"
  | "arrow";

const paths: Record<WorkspaceIconName, React.ReactNode> = {
  today: (
    <>
      <path d="m3 10 9-7 9 7v10H3Z" />
      <path d="M9 20v-7h6v7" />
    </>
  ),
  holdings: (
    <>
      <rect x="3" y="6" width="18" height="14" rx="2" />
      <path d="M8 6V4h8v2M3 11h18M10 11v3h4v-3" />
    </>
  ),
  analyze: (
    <>
      <path d="M4 3v17h17M8 15l4-6 4 3 5-8" />
    </>
  ),
  research: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5" />
    </>
  ),
  copilot: (
    <>
      <path d="M20 15a3 3 0 0 1-3 3H9l-5 3V6a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3Z" />
      <path d="M8 8h8M8 12h5" />
    </>
  ),
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
};

export function WorkspaceIcon({
  name,
  className = "h-5 w-5",
}: {
  name: WorkspaceIconName;
  className?: string;
}) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {paths[name]}
    </svg>
  );
}
