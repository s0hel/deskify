import type { Scanner } from "./index";

/** Browser fallback. The admin console never scans; this keeps tests honest. */
export const webScanner: Scanner = {
  async isAvailable() {
    return "BarcodeDetector" in globalThis;
  },
  async scan() {
    return null;
  },
};
