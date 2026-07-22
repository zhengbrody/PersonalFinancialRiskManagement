/** Remove query strings and fragments before an error leaves the app. */

import type { ErrorEvent } from "@sentry/nextjs";

export function stripUrlSecrets(value: string): string {
  return value.split(/[?#]/, 1)[0] ?? value;
}

export function scrubSentryEvent(event: ErrorEvent): ErrorEvent {
  if (event.request) {
    if (typeof event.request.url === "string") {
      event.request.url = stripUrlSecrets(event.request.url);
    }
    delete event.request.query_string;
    for (const [key, value] of Object.entries(event.request.headers ?? {})) {
      if (key.toLowerCase() === "referer") {
        event.request.headers![key] = stripUrlSecrets(value);
      }
    }
  }
  for (const crumb of event.breadcrumbs ?? []) {
    for (const key of ["url", "from", "to"]) {
      const value = crumb.data?.[key];
      if (typeof value === "string") crumb.data![key] = stripUrlSecrets(value);
    }
  }
  return event;
}
