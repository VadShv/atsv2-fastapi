/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone-сборка для Docker (минимальный образ)
  output: "standalone",

  // Проксинг API-запросов на бэкенд.
  // API_URL — серверная (non-public) переменная, доступна в runtime.
  // NEXT_PUBLIC_* инлайнятся при сборке и не подходят для server-side rewrites.
  async rewrites() {
    const apiBase = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiBase}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
