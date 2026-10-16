import { useEffect, useRef, type ReactNode } from 'react'
import type { ChatMessage } from '../../hooks/usePlanner'
import { useApp } from '../PlannerContext'
import { VOICE_ART } from '../voiceAssets'
import { Picture } from './VoiceHero'

function Avatar() {
  return (
    <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full bg-brand-50 ring-1 ring-brand-100">
      <Picture art={VOICE_ART.robot} alt="" className="h-7 w-7 object-contain" />
    </span>
  )
}

const BUBBLE: Record<ChatMessage['role'], string> = {
  user: 'rounded-br-md bg-brand-600 text-white',
  assistant: 'rounded-bl-md bg-white text-ink-900 ring-1 ring-ink-100',
  system: 'rounded-bl-md bg-amber-50 text-amber-900 ring-1 ring-amber-200',
}

function Bubble({ msg }: { msg: ChatMessage }) {
  const user = msg.role === 'user'
  return (
    <li data-testid="bubble" data-role={msg.role} className={`flex items-start gap-2 ${user ? 'justify-end' : 'justify-start'}`}>
      {!user && <Avatar />}
      <p className={`max-w-[82%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-card ${BUBBLE[msg.role]}`}>
        {msg.text}
      </p>
    </li>
  )
}

function Typing({ label }: { label: string }) {
  return (
    <li className="flex items-start gap-2" aria-label={label}>
      <Avatar />
      <span className="flex items-center gap-1 rounded-2xl rounded-bl-md bg-white px-4 py-3 shadow-card ring-1 ring-ink-100">
        {[0, 1, 2].map((i) => (
          <span key={i} aria-hidden className="h-2 w-2 animate-bounce rounded-full bg-brand-500 motion-reduce:animate-none" style={{ animationDelay: `${i * 150}ms` }} />
        ))}
        <span className="sr-only">{label}</span>
      </span>
    </li>
  )
}

/** ChatGPT-style thread: assistant on the left with the robot avatar, user on the right, typing dots while waiting. */
export function ChatThread({ messages, loading, children }: { messages: ChatMessage[]; loading: boolean; children?: ReactNode }) {
  const { m } = useApp()
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end', behavior: 'smooth' })
  }, [messages.length, loading])

  return (
    <section data-testid="chat-thread" className="flex-1 px-4 pb-4 pt-3">
      <ol role="log" aria-live="polite" aria-label={m.plan.conversation} className="space-y-3">
        {messages.map((msg) => <Bubble key={msg.id} msg={msg} />)}
        {loading && <Typing label={m.plan.typing} />}
      </ol>
      {children}
      <div ref={endRef} />
    </section>
  )
}
