declare module '@observablehq/inputs' {
  export function table(data: unknown[], options?: Record<string, unknown>): HTMLElement
  export function search(data: unknown[], options?: Record<string, unknown>): HTMLElement
  export function select(data: unknown[], options?: Record<string, unknown>): HTMLElement
  export function range(options?: Record<string, unknown>): HTMLElement
  export function checkbox(data: unknown[], options?: Record<string, unknown>): HTMLElement
  export function radio(data: unknown[], options?: Record<string, unknown>): HTMLElement
  export function text(options?: Record<string, unknown>): HTMLElement
  export function textarea(options?: Record<string, unknown>): HTMLElement
}
