/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone-сборка для Docker (минимальный образ)
  output: "standalone",

  // Path-prefix для reverse-proxy (Caddy на :3080 рутит /ats/* → этот контейнер).
  // Все внутренние ссылки и статики Next.js автоматически получают префикс /ats.
  basePath: "/ats",

  // Передаём basePath в клиентский код (для fetch-вызовов к API).
  env: {
    NEXT_PUBLIC_BASE_PATH: "/ats",
  },

  // Проксинг API-запросов на бэкенд.
  // API_URL — серверная (non-public) переменная, доступна в runtime.
  // С basePath /ats, source "/api/v1/:path*" матчит полный путь "/ats/api/v1/:path*".
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
