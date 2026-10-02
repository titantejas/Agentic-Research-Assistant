import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useRef, useState } from 'react';
import { streamChat } from '../api';
import { ToolTrace } from './ToolTrace';
export function ChatWindow() {
    const [msgs, setMsgs] = useState([]);
    const [input, setInput] = useState('');
    const [convId, setConvId] = useState(null);
    const [busy, setBusy] = useState(false);
    const abort = useRef(null);
    async function send() {
        if (!input.trim() || busy)
            return;
        const q = input;
        setInput('');
        setMsgs(m => [...m, { role: 'user', text: q, trace: [] }]);
        setBusy(true);
        abort.current = new AbortController();
        let acc = '', trace = [], cached = false;
        setMsgs(m => [...m, { role: 'assistant', text: '', trace: [] }]);
        try {
            for await (const evt of streamChat(q, convId, abort.current.signal)) {
                const t = evt.type;
                if (t === 'token')
                    acc += evt.data;
                else if (t === 'done') {
                    if (typeof evt.data === 'string' && !acc)
                        acc = evt.data;
                    if (evt.conversation_id)
                        setConvId(evt.conversation_id);
                }
                else {
                    trace = [...trace, evt];
                    if (t === 'cached')
                        cached = true;
                }
                setMsgs(m => { const c = [...m]; c[c.length - 1] = { role: 'assistant', text: acc, trace, cached }; return c; });
            }
        }
        catch (e) {
            acc += `\n[error: ${e.message}]`;
            setMsgs(m => { const c = [...m]; c[c.length - 1] = { role: 'assistant', text: acc, trace, cached }; return c; });
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("div", { style: { maxWidth: 800, margin: '0 auto', padding: 16, fontFamily: 'system-ui' }, children: [_jsx("h2", { children: "Agentic Research Assistant" }), _jsx("div", { children: msgs.map((m, i) => (_jsxs("div", { style: { background: m.role === 'user' ? '#dbeafe' : '#f1f5f9', padding: 10, borderRadius: 8, margin: '8px 0' }, children: [_jsx("div", { style: { whiteSpace: 'pre-wrap' }, children: m.text || '…' }), m.role === 'assistant' && _jsx(ToolTrace, { events: m.trace }), m.cached && _jsx("div", { style: { fontSize: 11, color: '#16a34a' }, children: "cached \u2022 35% latency saving" })] }, i))) }), _jsxs("div", { style: { display: 'flex', gap: 8 }, children: [_jsx("input", { value: input, onChange: e => setInput(e.target.value), onKeyDown: e => e.key === 'Enter' && send(), placeholder: "Ask a research question\u2026", style: { flex: 1, padding: 10 } }), _jsx("button", { onClick: send, disabled: busy, children: busy ? '…' : 'Send' })] })] }));
}
