import { Capacitor } from "@capacitor/core";

import type { Scanner } from "./index";

/**
 * Wraps @capacitor/barcode-scanner, which presents a NATIVE full-screen
 * scanner over the webview and returns the payload.
 *
 * It replaced @capacitor-mlkit/barcode-scanning, which pulled in GoogleMLKit
 * (TDD §10.2). Three reasons, and the third is the one that forced it:
 *
 *  1. We scan QR and nothing else -- PRD Q4 settled on "QR + geofence only",
 *     and FR-4.1/4.6 are both QR. ML Kit is a general on-device ML runtime
 *     carrying 13 symbologies to read the one iOS has decoded natively since
 *     iOS 7.
 *  2. ML Kit draws its camera preview BEHIND the webview, so the app had to
 *     turn its own background transparent to reveal it, and restore it on
 *     every path including the throwing one. This plugin owns the whole
 *     screen, so that hazard is gone rather than handled.
 *  3. GoogleMLKit ships fat .frameworks holding `x86_64 arm64` where arm64 is
 *     the DEVICE slice, so its podspec excludes arm64 for the simulator --
 *     in every release through 9.0.0. On an Apple Silicon Mac that means no
 *     arm64 simulator build of this app, ever. OSBarcodeLib, underneath this
 *     plugin, ships an xcframework with no such exclusion.
 *
 * The plugin is imported lazily so the web build never pulls it in, and so a
 * missing native binary surfaces as an unavailable scanner rather than a blank
 * screen on load.
 */

/** The plugin REJECTS for these; both mean "no code, and the user knows why".
 *  Matched on message because `call.reject` is invoked without an error code
 *  (see CapacitorBarcodeScannerPlugin.swift). Anything else is a real fault
 *  and is rethrown -- a scanner that silently returns nothing when the camera
 *  is broken is worse than one that fails. */
const USER_ENDED_SCAN = ["scanning cancelled", "camera access denied"];

export const capacitorScanner: Scanner = {
  async isAvailable() {
    // No isSupported() on this plugin: the native binary either registered or
    // it did not.
    return Capacitor.isNativePlatform() && Capacitor.isPluginAvailable("CapacitorBarcodeScanner");
  },

  async scan() {
    const mod = await import(/* @vite-ignore */ "@capacitor/barcode-scanner");
    const { CapacitorBarcodeScanner, CapacitorBarcodeScannerTypeHint } = mod;

    try {
      const { ScanResult } = await CapacitorBarcodeScanner.scanBarcode({
        // QR only. Widening this would accept any barcode on any object as a
        // check-in attempt.
        hint: CapacitorBarcodeScannerTypeHint.QR_CODE,
        scanInstructions: "Point the camera at the code on the desk",
        // The accessibility labels for the cancel and torch buttons arrived in
        // plugin 3.x, which peers on Capacitor 8; we are on 6. Until that
        // upgrade those two native controls are unlabelled for VoiceOver.
      });
      return ScanResult ?? null;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (USER_ENDED_SCAN.some((m) => message.toLowerCase().includes(m))) return null;
      throw err;
    }
  },
};
