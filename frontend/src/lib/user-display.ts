import type { User } from "@supabase/supabase-js";

/**
 * The label to show for a signed-in user in the UI (top-right account menu,
 * etc.). Prefers the user-chosen display name (Supabase
 * `user_metadata.username`, set on /settings); falls back to a neutral
 * "Account" so we never surface the email address in the chrome.
 */
export function displayName(user: Pick<User, "user_metadata">): string {
  const name = (user.user_metadata?.username as string | undefined)?.trim();
  return name || "Account";
}

/** The current username, or "" if none is set (for prefilling the settings form). */
export function currentUsername(user: Pick<User, "user_metadata">): string {
  return ((user.user_metadata?.username as string | undefined) ?? "").trim();
}
