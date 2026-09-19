import type { Scanner } from "./index";
import { withTransparentWebview } from "./index";

/**
 * Wraps @capacitor-mlkit/barcode-scanning.
 *
 * The plugin is imported lazily so the web build never pulls it in, and so a
 * missing native binary surfaces as an unavailable scanner rather than a blank
 * screen on load.
 */
export const capacitorScanner: Scanner = {
  async isAvailable() {
    try {
      const mod = await import(
        /* @vite-ignore */ "@capacitor-mlkit/barcode-scanning"
      );
      return (await mod.BarcodeScanner.isSupported()).supported;
    } catch {
      return false;
    }
  },

  async scan() {
    const mod = await import(/* @vite-ignore */ "@capacitor-mlkit/barcode-scanning");
    const { BarcodeScanner } = mod;
    const granted = await BarcodeScanner.requestPermissions();
    if (granted.camera !== "granted" && granted.camera !== "limited") return null;

    return withTransparentWebview(async () => {
      const { barcodes } = await BarcodeScanner.scan();
      return barcodes[0]?.rawValue ?? null;
    });
  },
};
