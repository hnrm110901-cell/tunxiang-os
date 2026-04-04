/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        tx: {
          bg: '#0B1A20',
          card: '#112228',
          border: '#1a2a33',
          hover: '#243540',
          accent: '#FF6B2C',
          'accent-light': 'rgba(255,107,44,0.15)',
          green: '#52c41a',
          'green-dark': '#0F6E56',
          blue: '#1890ff',
          danger: '#ff4d4f',
          warning: '#faad14',
          muted: '#8A94A4',
          'text-1': '#ffffff',
          'text-2': '#cccccc',
          'text-3': '#999999',
          'text-4': '#666666',
        },
        wechat: '#07C160',
        alipay: '#1677FF',
        unionpay: '#e6002d',
      },
      borderRadius: {
        tx: '12px',
        'tx-sm': '8px',
        'tx-lg': '16px',
      },
      fontFamily: {
        tx: ['-apple-system', 'BlinkMacSystemFont', '"PingFang SC"', '"Helvetica Neue"', 'sans-serif'],
      },
      minHeight: {
        'touch': '48px',
      },
    },
  },
  plugins: [],
}
