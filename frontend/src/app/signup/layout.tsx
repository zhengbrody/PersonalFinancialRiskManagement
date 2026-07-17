import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Create a portfolio risk workspace",
  description: "Create a MindMarket account and start a connected portfolio risk workflow.",
  alternates: { canonical: "/signup" },
  robots: { index: false, follow: false },
};

export default function SignupLayout({ children }: { children: React.ReactNode }) {
  return children;
}
