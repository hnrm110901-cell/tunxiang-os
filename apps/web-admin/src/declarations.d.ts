// Ambient module declarations for packages without type definitions
declare module 'dompurify' {
  interface DOMPurify {
    sanitize(dirty: string, options?: Record<string, unknown>): string;
  }
  const DOMPurify: DOMPurify;
  export default DOMPurify;
}
