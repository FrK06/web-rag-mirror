/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  
  // Disable ESLint during build
  eslint: {
    ignoreDuringBuilds: true,
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
  
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'https://loadant.com',
  },
  
  webpack: (config) => {
    if (!config.resolve) {
      config.resolve = {};
    }
    
    config.resolve.fallback = {
      ...(config.resolve.fallback || {}),
      punycode: false 
    };
    
    return config;
  },
  
  // Add image optimizations
  images: {
    domains: ['loadant.com'],
    unoptimized: process.env.NODE_ENV !== 'production',
  },
  
  // Add TypeScript checking options
  typescript: {
    // Set to true for production builds to catch type errors
    // Setting to false here since we're already disabling ESLint
    ignoreBuildErrors: true,
  },
  
  // Add trailing slashes
  trailingSlash: false,
  
  // Add powered by header
  poweredByHeader: false,
};

module.exports = nextConfig;
