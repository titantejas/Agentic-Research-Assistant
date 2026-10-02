import React, { useRef, useState } from 'react';
import { streamChat } from '../api';
import { ToolTrace } from './ToolTrace';

type Msg = { role: 'user' | 'assistant'; text: string; trace: any[]; cached?: boolean };

export function ChatWindow() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [convId, setConvId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);

  async function send() {
    if (!input.trim() || busy) return;
    const q = input; setInput('');
    setMsgs(m => [...m, { role: 'user', text: q, trace: [] }]);
    setBusy(true);
    abort.current = new AbortController();
    let acc = '', trace: any[] = [], cached = false;
    setMsgs(m => [...m, { role: 'assistant', text: '', trace: [] }]);
    try {
      for await (const evt of streamChat(q, convId, abort.current.signal)) {
        const t = (evt as any).type;
        if (t === 'token') acc += (evt as any).data;
        else if (t === 'done') {
          if (typeof (evt as any).data === 'string' && !acc) acc = (evt as any).data;
          if ((evt as any).conversation_id) setConvId((evt as any).conversation_id);
        }
        else { trace = [...trace, evt]; if (t === 'cached') cached = true; }
        setMsgs(m => { const c = [...m]; c[c.length-1] = { role: 'assistant', text: acc, trace, cached }; return c; });
      }
    } catch (e) { acc += `\n[error: ${(e as Error).message}]`; setMsgs(m => { const c=[...m]; c[c.length-1]={role:'assistant',text:acc,trace,cached}; return c; }); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 16, fontFamily: 'system-ui' }}>
      <h2>Agentic Research Assistant</h2>
      <div>
        {msgs.map((m, i) => (
          <div key={i} style={{ background: m.role === 'user' ? '#dbeafe' : '#f1f5f9', padding: 10, borderRadius: 8, margin: '8px 0' }}>
            <div style={{ whiteSpace: 'pre-wrap' }}>{m.text || '…'}</div>
            {m.role === 'assistant' && <ToolTrace events={m.trace} />}
            {m.cached && <div style={{ fontSize: 11, color: '#16a34a' }}>cached • 35% latency saving</div>}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key==='Enter'&&send()}
          placeholder="Ask a research question…" style={{ flex: 1, padding: 10 }} />
        <button onClick={send} disabled={busy}>{busy ? '…' : 'Send'}</button>
      </div>
    </div>
  );
}
