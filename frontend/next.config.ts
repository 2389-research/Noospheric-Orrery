import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Set NEXT_OUTPUT=standalone for the Tauri desktop build (Noospheric repo),
  // which runs the frontend as `node server.js` from .next/standalone.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  allowedDevOrigins: ["disaster.porpoise-alkaline.ts.net"],
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8100";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
