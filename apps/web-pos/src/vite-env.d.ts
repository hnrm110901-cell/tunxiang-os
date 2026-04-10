/// <reference types="vite/client" />

declare module '*.module.css' {
  const classes: Record<string, string>;
  export default classes;
}

// @ant-design/icons — stub until package is installed
declare module '@ant-design/icons' {
  import type { FC } from 'react';
  export const BgColorsOutlined: FC;
  export const UnorderedListOutlined: FC;
  export const EnvironmentOutlined: FC;
  export const ReloadOutlined: FC;
}
