import { describe, expect, it } from "vitest";
import { scrubSentryEvent, stripUrlSecrets } from "./sentry-scrub";

describe("Sentry URL redaction", () => {
  it("strips query strings and fragments from absolute and relative URLs", () => {
    expect(stripUrlSecrets("https://mindmarket.app/share?token=secret#x")).toBe("https://mindmarket.app/share");
    expect(stripUrlSecrets("/share?token=secret")).toBe("/share");
  });

  it("scrubs request, referrer and navigation breadcrumbs", () => {
    const event = scrubSentryEvent({
      type: undefined,
      request: { url: "/share?token=secret#x", query_string: "token=secret", headers: { Referer: "/from?token=secret" } },
      breadcrumbs: [{ data: { url: "/to?token=secret", from: "/a#x", to: "/b?q=1" } }],
    });
    expect(event.request?.url).toBe("/share");
    expect(event.request).not.toHaveProperty("query_string");
    expect(event.request?.headers?.Referer).toBe("/from");
    expect(event.breadcrumbs?.[0].data).toEqual({ url: "/to", from: "/a", to: "/b" });
  });
});
