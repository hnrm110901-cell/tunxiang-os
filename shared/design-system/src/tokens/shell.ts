/**
 * 屯象OS · 终端 Shell Token
 * 不同终端的触控/字号差异通过 Shell CSS Class 控制
 */
export const shellTokens = {
  pos: {
    '--tx-touch-min': '56px',
    '--tx-font-body': '14px',
    '--tx-font-dish-name': '18px',
    '--tx-font-price': '16px',
    '--tx-card-gap': '10px',
    '--tx-cart-width': '320px',
  },
  kds: {
    '--tx-touch-min': '64px',
    '--tx-font-body': '16px',
    '--tx-font-dish-name': '24px',
    '--tx-font-price': '20px',
    '--tx-card-gap': '12px',
    '--tx-cart-width': '0px',
  },
  crew: {
    '--tx-touch-min': '48px',
    '--tx-font-body': '16px',
    '--tx-font-dish-name': '16px',
    '--tx-font-price': '14px',
    '--tx-card-gap': '8px',
    '--tx-cart-width': '0px',
  },
  h5: {
    '--tx-touch-min': '44px',
    '--tx-font-body': '14px',
    '--tx-font-dish-name': '16px',
    '--tx-font-price': '14px',
    '--tx-card-gap': '8px',
    '--tx-cart-width': '0px',
  },
  admin: {
    '--tx-touch-min': '32px',
    '--tx-font-body': '13px',
    '--tx-font-dish-name': '14px',
    '--tx-font-price': '13px',
    '--tx-card-gap': '8px',
    '--tx-cart-width': '0px',
  },
} as const;

export type ShellType = keyof typeof shellTokens;
