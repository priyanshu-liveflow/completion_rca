import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],

  // Dev-only: never let a browser cache a build asset.
  //
  // Next reuses the same chunk filename across edits in development, so a
  // stylesheet URL that returned one thing yesterday returns another today
  // with no name change to signal it. A browser holding the old copy renders
  // a half-styled page — new class names present in the markup, no rules
  // behind them — which reads as "the CSS is broken" rather than "the CSS is
  // stale", and survives an ordinary reload because the URL never changed.
  //
  // Costs nothing in dev, where assets are served from memory anyway, and is
  // skipped in production, where filenames are content-hashed and long-lived
  // caching is the point.
  async headers() {
    if (process.env.NODE_ENV === "production") return [];
    return [
      {
        source: "/_next/static/:path*",
        headers: [
          { key: "Cache-Control", value: "no-store, must-revalidate" },
          { key: "Pragma", value: "no-cache" },
        ],
      },
    ];
  },
};

export default nextConfig;
