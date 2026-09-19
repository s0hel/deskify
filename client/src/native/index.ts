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
