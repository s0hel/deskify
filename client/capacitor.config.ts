import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "app.deskify.client",
  appName: "Deskify",
  webDir: "dist",
  // NO `server.url`. The bundle ships INSIDE the binary: that is what makes
  // offline work (FR-10.1) and keeps us clear of App Store guideline 4.2
  // (TDD §8 / PRD §8.1.2 condition 3). Do not add a remote URL here to get
  // faster updates -- see the OTA decision, TDD §17.2 T1.
  plugins: {
    Keyboard: { resize: "native" },
    PushNotifications: { presentationOptions: ["badge", "sound", "alert"] },
  },
};

export default config;
