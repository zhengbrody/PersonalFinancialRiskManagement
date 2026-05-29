/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output bundles ONLY the files the production server
  // needs into `.next/standalone`. Drops the rest of node_modules,
  // shrinking the Docker image from ~1 GB (full Next + react + every
  // transitive) to ~200 MB. The runtime stage in `Dockerfile` copies
  // standalone + `.next/static` + `public/` and runs `node server.js`.
  //
  // Safe to keep on for dev too — `next dev` ignores this setting.
  output: "standalone",
};

export default nextConfig;
