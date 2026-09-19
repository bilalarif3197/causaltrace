import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev-only. Lets the app be opened through a local proxy or preview tunnel
  // (e.g. http://127.0.0.1:<port>) without HMR being blocked as cross-origin.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
