import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Pin the workspace root to this app — an unrelated lockfile at /root
  // otherwise makes Next.js guess (and warn) about the wrong root.
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
