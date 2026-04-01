import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
