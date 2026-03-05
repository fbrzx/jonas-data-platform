import { useState, useRef, useEffect } from 'react'
import { api, type ChatMessage, DEMO_TOKENS, getToken, setToken, getRoleFromToken } from '../lib/api'

// ── Code block ────────────────────────────────────────────────────────────────

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="my-3 rounded overflow-hidden border border-j-border">
      <div className="flex items-center justify-between px-3 py-1.5 bg-j-surface2 border-b border-j-border">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-j-accent opacity-70" />
          <span className="font-mono text-[10px] font-semibold tracking-[0.12em] uppercase text-j-dim">
            {lang || 'code'}
          </span>
        </div>
        <button
          onClick={copy}
          className="font-mono text-[10px] text-j-dim hover:text-j-accent transition-colors tracking-wider"
        >
          {copied ? 'copied' : 'copy'}
        </button>
      </div>
      <pre className="bg-j-surface px-4 py-3 overflow-x-auto text-[12.5px] font-mono leading-relaxed text-j-text">
        <code>{code}</code>
      </pre>
    </div>
  )
}

function InlineText({ text }: { text: string }) {
  return (
    <>
      {text.split('\n').map((line, i) => {
        if (!line.trim()) return <div key={i} className="h-2" />
        if (line.startsWith('### '))
          return <p key={i} className="font-semibold text-j-bright mt-3 mb-1">{line.slice(4)}</p>
        if (line.startsWith('## '))
          return <p key={i} className="font-semibold text-j-bright mt-4 mb-1">{line.slice(3)}</p>
        if (line.startsWith('- ') || line.startsWith('* '))
          return (
            <div key={i} className="flex gap-2 ml-2 text-j-text">
              <span className="text-j-dim mt-0.5">·</span>
              <span>{formatInline(line.slice(2))}</span>
            </div>
          )
        return <p key={i} className="leading-relaxed text-j-text">{formatInline(line)}</p>
      })}
    </>
  )
}

function formatInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = []
  const re = /(\*\*(.+?)\*\*|`([^`]+)`)/g
  let last = 0, m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    if (m[0].startsWith('**'))
      parts.push(<strong key={m.index} className="text-j-bright font-semibold">{m[2]}</strong>)
    else
      parts.push(
        <code key={m.index} className="bg-j-surface2 text-j-accent px-1.5 py-0.5 rounded text-[11px] font-mono border border-j-border">
          {m[3]}
        </code>
      )
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

function renderContent(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  const fenceRegex = /```(\w*)\n?([\s\S]*?)```/g
  let last = 0, match: RegExpExecArray | null
  while ((match = fenceRegex.exec(text)) !== null) {
    if (match.index > last)
      parts.push(<InlineText key={`t-${last}`} text={text.slice(last, match.index)} />)
    parts.push(<CodeBlock key={`c-${match.index}`} lang={match[1]} code={match[2].trimEnd()} />)
    last = match.index + match[0].length
  }
  if (last < text.length)
    parts.push(<InlineText key="t-end" text={text.slice(last)} />)
  return parts
}

// ── Message bubble ────────────────────────────────────────────────────────────

function Message({ msg, idx }: { msg: ChatMessage; idx: number }) {
  const isUser = msg.role === 'user'
  return (
    <div className="fade-up flex gap-3 mb-5" style={{ animationDelay: `${idx * 20}ms` }}>
      <div
        className={`shrink-0 w-6 h-6 rounded font-mono text-[10px] font-semibold flex items-center justify-center mt-0.5 ${
          isUser
            ? 'bg-j-accent-dim text-j-accent border border-j-accent'
            : 'bg-j-surface2 text-j-dim border border-j-border'
        }`}
      >
        {isUser ? 'U' : 'J'}
      </div>
      <div className="flex-1 min-w-0">
        <div className={`font-mono text-[10px] tracking-[0.1em] uppercase mb-1.5 ${isUser ? 'text-j-accent' : 'text-j-dim'}`}>
          {isUser ? 'you' : 'jonas'}
        </div>
        <div className={`text-sm rounded p-3 border ${
          isUser
            ? 'bg-j-accent-dim border-j-accent-dim text-j-bright'
            : 'bg-j-surface border-j-border text-j-text'
        }`}>
          {isUser
            ? <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
            : renderContent(msg.content)
          }
        </div>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

const STARTERS = [
  'What datasets are in the catalogue?',
  'Show me tables in the bronze layer',
  'List all approved transforms',
  'Which fields contain PII data?',
]

interface ChatPageProps {
  messages: ChatMessage[]
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>
  input: string
  setInput: React.Dispatch<React.SetStateAction<string>>
}

export default function ChatPage({ messages, setMessages, input, setInput }: ChatPageProps) {
  const [token, setTokenState] = useState(getToken)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const role = getRoleFromToken(token)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  const handleTokenChange = (t: string) => { setToken(t); setTokenState(t); setMessages([]); setError(null) }
  const handleNewChat = () => { setMessages([]); setInput(''); setError(null) }

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return
    const userMsg: ChatMessage = { role: 'user', content: text }
    const next = [...messages, userMsg]
    setMessages(next); setInput(''); setError(null); setLoading(true)

    let streamedContent = ''
    let hasStartedText = false

    try {
      for await (const event of api.agent.streamChat(next)) {
        if (event.type === 'delta' && event.text) {
          streamedContent += event.text
          if (!hasStartedText) {
            hasStartedText = true
            setLoading(false)
            setMessages([...next, { role: 'assistant', content: streamedContent }])
          } else {
            setMessages(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = { role: 'assistant', content: streamedContent }
              return updated
            })
          }
        } else if (event.type === 'error') {
          throw new Error(event.message ?? 'Stream error')
        }
      }
      // If no text was streamed (e.g. pure tool call with no final text), ensure loading is off
      if (!hasStartedText) {
        setLoading(false)
      }
    } catch (e) {
      setLoading(false)
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setTimeout(() => textareaRef.current?.focus(), 50)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const ROLE_COLORS: Record<string, string> = {
    admin:   'bg-j-purple-dim text-j-purple border-j-purple',
    analyst: 'bg-j-accent-dim text-j-accent border-j-accent',
    viewer:  'bg-j-surface2 text-j-dim border-j-border',
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-j-bg">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3.5 border-b border-j-border bg-j-surface grid-bg shrink-0">
        <div>
          <span className="font-mono text-[11px] font-medium tracking-[0.15em] uppercase text-j-accent">
            Chat
          </span>
          <span className="font-mono text-[11px] text-j-dim ml-3">Ask questions about your data</span>
        </div>
        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <button
              onClick={handleNewChat}
              className="px-3 py-1 font-mono text-[10px] tracking-[0.1em] uppercase rounded border border-j-border text-j-dim hover:border-j-accent hover:text-j-accent transition-colors"
              title="Clear conversation and start fresh"
            >
              + New
            </button>
          )}
          {DEMO_TOKENS.map((t) => (
            <button
              key={t.value}
              onClick={() => handleTokenChange(t.value)}
              className={`px-3 py-1 font-mono text-[10px] tracking-[0.1em] uppercase rounded border transition-colors ${
                token === t.value
                  ? 'bg-j-accent-dim text-j-accent border-j-accent'
                  : 'bg-j-surface2 text-j-dim border-j-border hover:border-j-border-b hover:text-j-text'
              }`}
            >
              {t.label}
            </button>
          ))}
          <span className={`ml-1 px-2 py-0.5 rounded font-mono text-[10px] border ${ROLE_COLORS[role] ?? ROLE_COLORS.viewer}`}>
            {role}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mb-6">
              Jonas · AI assistant
            </div>
            <div className="grid grid-cols-2 gap-2 max-w-lg w-full">
              {STARTERS.map((s) => (
                <button
                  key={s}
                  onClick={() => { setInput(s); textareaRef.current?.focus() }}
                  className="text-left px-3 py-2.5 rounded border border-j-border bg-j-surface text-j-dim text-xs font-mono hover:border-j-accent hover:text-j-accent hover:bg-j-accent-dim transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => <Message key={i} msg={msg} idx={i} />)}

        {loading && (
          <div className="flex gap-3 mb-5">
            <div className="shrink-0 w-6 h-6 rounded bg-j-surface2 border border-j-border flex items-center justify-center font-mono text-[10px] text-j-dim mt-0.5">J</div>
            <div className="mt-0.5">
              <div className="font-mono text-[10px] text-j-dim tracking-[0.1em] uppercase mb-1.5">jonas</div>
              <div className="flex gap-1 items-center h-6 px-3 bg-j-surface border border-j-border rounded">
                {[0, 1, 2].map((i) => (
                  <span key={i} className="w-1.5 h-1.5 rounded-full bg-j-green bounce-dot" style={{ animationDelay: `${i * 180}ms` }} />
                ))}
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="mb-4 px-4 py-2.5 rounded border border-j-red-dim bg-j-red-dim font-mono text-xs text-j-red">
            error · {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t border-j-border bg-j-surface shrink-0">
        <div className="flex gap-3 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your data… (Enter to send, Shift+Enter for newline)"
            rows={4}
            className="flex-1 resize-y min-h-[6rem] rounded border border-j-border bg-j-surface2 text-j-text text-sm font-mono px-3 py-2.5 placeholder-j-dim focus:outline-none focus:border-j-accent transition-colors"
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || loading}
            className="px-4 py-2.5 rounded border border-j-accent bg-j-accent-dim text-j-accent font-mono text-[11px] tracking-[0.1em] uppercase hover:bg-j-accent hover:text-j-bg disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            Send
          </button>
        </div>
        <p className="font-mono text-[10px] text-j-dim mt-2">↵ send · shift+↵ newline · full history sent each turn</p>
      </div>
    </div>
  )
}
