// The backend URL is inlined at build time.
// NEXT_PUBLIC_API_URL is the Next.js name; VITE_API_URL is read too so the
// variable already set in the Vercel project for the old Vite build keeps
// working without touching the dashboard.
const apiUrl =
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.VITE_API_URL ||
  (process.env.NODE_ENV === 'development'
    ? 'http://localhost:8000'
    : 'https://stockvision-pro-jbve.onrender.com');

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: apiUrl.replace(/\/$/, ''),
  },
};

export default nextConfig;