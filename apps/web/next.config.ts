import type { NextConfig } from "next";

// Where the Next.js server reaches the FastAPI backend (http://api:8000 inside Docker).
const apiInternalUrl = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  output: "standalone", // minimal self-contained server for the Docker image
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // The browser talks only to this origin; /api/v1/* is forwarded to FastAPI. Same-origin keeps
  // auth cookies first-party and avoids CORS (BLUEPRINT D10). In deployed environments Caddy
  // routes /api/* directly, so this rewrite mainly serves local development.
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiInternalUrl}/api/v1/:path*` }];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
