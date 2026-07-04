"use client";

/**
 * /settings — weekly risk digest toggle. Default is ON (opt-out model, the
 * email itself carries a one-click unsubscribe). Fail-soft: while the 0007
 * tables aren't applied the GET errors → we render nothing rather than a
 * broken toggle.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useDigestPref, useSetDigestPref } from "@/lib/queries";

export function WeeklyDigestCard() {
  const pref = useDigestPref();
  const setPref = useSetDigestPref();

  if (pref.isError) return null;
  const enabled = pref.data?.enabled ?? true;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Weekly risk digest</CardTitle>
        <CardDescription>
          每周一早上一封邮件:你的 Health Score 变化、波动、集中度和市场状态 —
          全部来自你自己最近一次评分的确定性数字,教育性内容,随时可退订。
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          状态:{" "}
          <span className={enabled ? "font-medium text-[hsl(var(--success))]" : "text-muted-foreground"}>
            {pref.isLoading ? "…" : enabled ? "已开启" : "已关闭"}
          </span>
        </p>
        <Button
          variant={enabled ? "outline" : "default"}
          size="sm"
          disabled={pref.isLoading || setPref.isPending}
          onClick={() => setPref.mutate(!enabled)}
        >
          {setPref.isPending ? "保存中…" : enabled ? "关闭简报" : "开启简报"}
        </Button>
        {setPref.isError && (
          <p className="w-full text-xs text-destructive">保存失败,请稍后重试。</p>
        )}
      </CardContent>
    </Card>
  );
}
