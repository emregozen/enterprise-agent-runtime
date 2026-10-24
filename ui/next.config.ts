import type { NextConfig } from "next";

const controlPlane = process.env.CONTROL_PLANE_URL || "http://127.0.0.1:8841";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${controlPlane}/:path*` }];
  },
};

export default nextConfig;
