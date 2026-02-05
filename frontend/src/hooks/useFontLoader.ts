/* Copyright 2026 Marimo. All rights reserved. */
import { useLayoutEffect, useState } from "react";
import { getFeatureFlag } from "@/core/config/feature-flag";
import { Logger } from "@/utils/Logger";

type FontStatus = "idle" | "loading" | "loaded" | "error";

// CDN URLs (fontsource packages)
const LILEX_CSS =
  "https://cdn.jsdelivr.net/npm/@fontsource/lilex@5.2.1/index.min.css";
const GEIST_SANS_300 =
  "https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/300.min.css";
const GEIST_SANS_400 =
  "https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/400.min.css";
const GEIST_SANS_700 =
  "https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/700.min.css";

function loadStylesheet(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`link[href="${url}"]`)) {
      resolve();
      return;
    }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = url;
    link.onload = () => resolve();
    link.onerror = () => reject(new Error(`Failed to load: ${url}`));
    document.head.appendChild(link);
  });
}

/**
 * Hook that loads custom fonts (Lilex for code, Geist Sans for UI)
 * when the custom_fonts feature flag is enabled.
 */
export function useFontLoader(): FontStatus {
  const [status, setStatus] = useState<FontStatus>("idle");

  useLayoutEffect(() => {
    if (!getFeatureFlag("custom_fonts")) {
      return;
    }

    setStatus("loading");

    Promise.all([
      loadStylesheet(LILEX_CSS),
      loadStylesheet(GEIST_SANS_300),
      loadStylesheet(GEIST_SANS_400),
      loadStylesheet(GEIST_SANS_700),
    ])
      .then(() => {
        document.documentElement.style.setProperty(
          "--marimo-monospace-font",
          '"Lilex", monospace',
        );
        document.documentElement.style.setProperty(
          "--marimo-text-font",
          '"Geist Sans", sans-serif',
        );
        setStatus("loaded");
      })
      .catch((err) => {
        Logger.error("Font loading failed:", err);
        setStatus("error");
      });
  }, []);

  return status;
}
