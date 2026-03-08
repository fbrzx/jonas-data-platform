import { createContext, useCallback, useContext, useState } from 'react'

type ToastKind = 'success' | 'error' | 'info'

interface ToastItem {
  id: number
  kind: ToastKind
  message: string
}

interface ConfirmState {
  message: string
  resolve: (val: boolean) => void
}

interface ToastCtx {
  toast: (kind: ToastKind, message: string) => void
  confirm: (message: string) => Promise<boolean>
}

const Ctx = createContext<ToastCtx>({
  toast: () => {},
  confirm: async () => false,
})

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null)

  const toast = useCallback((kind: ToastKind, message: string) => {
    const id = Date.now()
    setToasts((t) => [...t, { id, kind, message }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])

  const confirm = useCallback((message: string): Promise<boolean> => {
    return new Promise((resolve) => setConfirmState({ message, resolve }))
  }, [])

  function handleConfirm(val: boolean) {
    confirmState?.resolve(val)
    setConfirmState(null)
  }

  const kindClass: Record<ToastKind, string> = {
    success: 'bg-j-green-dim border-j-green text-j-green',
    error:   'bg-j-red-dim   border-j-red   text-j-red',
    info:    'bg-j-surface   border-j-border text-j-text',
  }

  return (
    <Ctx.Provider value={{ toast, confirm }}>
      {children}

      {/* ── Toast stack ──────────────────────────────────────────────── */}
      <div className="fixed bottom-5 right-5 z-[100] flex flex-col gap-2 max-w-xs w-full pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`px-4 py-2.5 rounded border font-mono text-[11px] leading-relaxed shadow-lg pointer-events-auto fade-up ${kindClass[t.kind]}`}
          >
            {t.message}
          </div>
        ))}
      </div>

      {/* ── Confirm dialog ──────────────────────────────────────────── */}
      {confirmState && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60">
          <div className="bg-j-surface border border-j-border rounded-lg overflow-hidden shadow-2xl max-w-sm w-full mx-4">
            <div className="px-5 py-4">
              <p className="font-mono text-sm text-j-text leading-relaxed">{confirmState.message}</p>
            </div>
            <div className="flex gap-2 justify-end px-5 pb-4">
              <button
                onClick={() => handleConfirm(false)}
                className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim border border-j-border px-3 py-1.5 rounded hover:border-j-border-b transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleConfirm(true)}
                className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-red border border-j-red px-3 py-1.5 rounded hover:bg-j-red hover:text-j-bg transition-colors"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </Ctx.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  return useContext(Ctx)
}
