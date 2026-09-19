/**
 * Every Capacitor plugin call lives behind an interface here, with a web
 * implementation alongside (TDD §10.2).
 *
 * Three reasons, in order: the admin console runs in a browser with no
 * plugins; component tests run in jsdom; and swapping a plugin -- likely at
 * least once -- becomes a one-file change.
 */

import { Capacitor } from "@capacitor/core";

export interface Scanner {
  /** Resolves with the raw QR payload, or null if the user cancelled. */
  scan(): Promise<string | null>;
  isAvailable(): Promise<boolean>;
}

export interface Position {
  lat: number;
  lng: number;
}

export interface Geo {
  /** One-shot FOREGROUND read. There is no background mode by design:
   *  the user is in the app when they check in (TDD §8.2). */
  currentPosition(): Promise<Position | null>;
}

export interface SecureStore {
  /** Keychain / Keystore. NEVER @capacitor/preferences -- that is plaintext
   *  on disk (PRD §8.1.1). */
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}

export const isNative = (): boolean => Capacitor.isNativePlatform();

/**
 * The scanning screen makes the webview transparent so the native camera
 * preview behind it is visible, and draws its own reticle in HTML.
 *
 * The restore MUST run on the error path too. A webview left transparent is an
 * app that looks broken (PRD §8.1.2 condition 2).
 */
export async function withTransparentWebview<T>(fn: () => Promise<T>): Promise<T> {
  document.body.classList.add("scanner-active");
  try {
    return await fn();
  } finally {
    document.body.classList.remove("scanner-active");
  }
}
