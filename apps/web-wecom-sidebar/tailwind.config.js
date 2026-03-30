/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // 屯象OS Design Token
        'tx-primary':    '#FF6B35',
        'tx-primary-active': '#E55A28',
        'tx-primary-light':  '#FFF3ED',
        'tx-navy':       '#1E2A3A',
        'tx-success':    '#0F6E56',
        'tx-warning':    '#BA7517',
        'tx-danger':     '#A32D2D',
        'tx-info':       '#185FA5',
        'tx-text-1':     '#2C2C2A',
        'tx-text-2':     '#5F5E5A',
        'tx-text-3':     '#B4B2A9',
        'tx-border':     '#E8E6E1',
        'tx-bg-1':       '#FFFFFF',
        'tx-bg-2':       '#F8F7F5',
        'tx-bg-3':       '#F0EDE6',
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"PingFang SC"',
          '"Helvetica Neue"',
          '"Microsoft YaHei"',
          'sans-serif',
        ],
      },
      maxWidth: {
        sidebar: '375px',
      },
      borderRadius: {
        'tx-sm': '4px',
        'tx-md': '6px',
        'tx-lg': '8px',
      },
      boxShadow: {
        'tx-sm': '0 1px 2px rgba(0,0,0,0.05)',
        'tx-md': '0 4px 12px rgba(0,0,0,0.08)',
        'tx-lg': '0 8px 24px rgba(0,0,0,0.12)',
      },
    },
  },
  plugins: [],
};
