/** Static export: deployed to Azure Static Web Apps, talks to the API over HTTPS. */
const nextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};
export default nextConfig;
