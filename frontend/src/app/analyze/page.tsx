import { Suspense } from "react";
import type { Metadata } from "next";
import { AnalyzeWorkspace } from "@/components/analyze-workspace";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = {
  title: "Analyze · MindMarket",
  description: "Your unified risk workspace — diagnose, stress-test, plan and review.",
  robots: { index: false, follow: false }, // signed-in workspace
};

export default function AnalyzePage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <AnalyzeWorkspace />
    </Suspense>
  );
}
