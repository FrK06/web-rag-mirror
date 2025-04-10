/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  
  // Disable ESLint during build
  eslint: {
    ignoreDuringBuilds: true,
  },
  
  // Configure API rewrites to proxy requests to Railway backend
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'https://auth-service-58a543c5-5a59-41e7-bee8-b8fb581add47.railway.app/api/:path*',
      },
    ];
  },
  
  // Configure security headers
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-XSS-Protection', value: '1; mode=block' },
          {
            key: 'Content-Security-Policy',
            value: `default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; connect-src 'self' https://loadant.com;`,
          },
        ],
      },
    ];
  },
  
  // Use Vercel's image optimization
  images: {
    domains: ['loadant.com'],
  },
  
  // Disable TS errors during build
  typescript: {
    ignoreBuildErrors: true,
  },
  
  // Misc optimizations
  poweredByHeader: false,
};

module.exports = nextConfig;
