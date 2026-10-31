export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const AUTH_MODE = (process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev") as "dev" | "entra";
export const ENTRA = {
  clientId: process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID ?? "",
  tenantId: process.env.NEXT_PUBLIC_ENTRA_TENANT_ID ?? "",
  scope: process.env.NEXT_PUBLIC_ENTRA_API_SCOPE ?? "",
};
