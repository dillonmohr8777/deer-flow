"use client";

import { useEffect } from "react";

import { registerPublicServiceWorker } from "@/core/pwa/install";

import { InstallHelp } from "./install-help";

export function PwaBoundary() {
  useEffect(() => {
    // Leave development/HMR unmodified. Production and packaged web apps share
    // the same public-only offline policy; registration failure is non-blocking.
    if (process.env.NODE_ENV !== "production") return;
    void registerPublicServiceWorker().catch(() => {
      console.warn("MomoBot offline connection screen could not be enabled.");
    });
  }, []);

  return <InstallHelp />;
}
