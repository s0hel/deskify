/**
 * Sign-in. TDD §6.2.
 *
 * The real flow opens `start_url` in the SYSTEM browser via @capacitor/browser,
 * and the IdP redirects back to a Universal Link carrying a one-time code,
 * which the app redeems here. That leg needs Google/Entra client credentials
 * (open question T6), so in dev the API hands out the same one-time code from
 * /auth/dev-sign-in.
 *
 * The important part is that everything AFTER the code is the real path:
 * redeem over HTTPS, hold the access token in memory, never in a URL. When the
 * real IdP arrives, only `signIn` changes.
 */

import { api, setAccessToken } from "../api/client";

export interface Discovery {
  region: string;
  idp_kind: "google" | "entra" | "magic_link";
  start_url: string;
}

export interface Me {
  user_id: string;
  organization_id: string;
  email: string;
  display_name: string;
}

export async function discover(email: string): Promise<Discovery> {
  return api<Discovery>("/auth/discover", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

async function redeem(code: string): Promise<Me> {
  const { access_token } = await api<{ access_token: string }>("/auth/token", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
  // In memory only. The refresh token is what goes to the Keychain/Keystore on
  // native, and to an httpOnly cookie on web (TDD §6.3).
  setAccessToken(access_token);
  return api<Me>("/me");
}

export async function signIn(email: string): Promise<Me> {
  await discover(email); // routes the tenant; the real flow does this first too
  const { code } = await api<{ code: string }>("/auth/dev-sign-in", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  return redeem(code);
}

export function signOut() {
  setAccessToken(null);
}
