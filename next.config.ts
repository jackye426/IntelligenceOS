import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow server-side modules (playwright, pg-boss) to be excluded from client bundles
  serverExternalPackages: ["playwright", "pg-boss"],
};

export default nextConfig;
