import type { Role } from "./types";

/** Decode (not verify) a JWT payload for display purposes. The API verifies every token; the UI only needs the role. */
export function decodeClaims(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(decodeURIComponent(escape(json))) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function roleFromToken(token: string): Role | null {
  const roles = decodeClaims(token)?.roles;
  if (Array.isArray(roles) && roles.length === 1 && ["patient", "provider", "reviewer"].includes(String(roles[0]))) {
    return roles[0] as Role;
  }
  return null;
}

export function isExpired(token: string, skewSeconds = 30): boolean {
  const exp = decodeClaims(token)?.exp;
  return typeof exp !== "number" || exp * 1000 < Date.now() + skewSeconds * 1000;
}
