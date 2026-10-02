export async function* streamChat(query, conversationId, signal) {
    const res = await fetch('http://localhost:8000/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, conversation_id: conversationId }),
        signal,
    });
    if (!res.body)
        throw new Error('No body');
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
        const { done, value } = await reader.read();
        if (done)
            break;
        buf += dec.decode(value, { stream: true });
        // SSE frames: "data: {...}\n\n"
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
            const frame = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const line = frame.split('\n').find(l => l.startsWith('data:'));
            if (!line)
                continue;
            const payload = line.slice(5).trim();
            if (payload === '[DONE]')
                return;
            try {
                const evt = JSON.parse(JSON.parse(payload).data ?? payload);
                // sse-starlette double-wraps; handle both
                yield evt;
            }
            catch {
                try {
                    yield JSON.parse(payload);
                }
                catch { /* keep */ }
            }
        }
    }
}
