import React from 'react';

export function ToolTrace({ events }: { events: any[] }) {
  if (!events.length) return null;
  return (
    <div style={{ background: '#0f172a', color: '#e2e8f0', borderRadius: 8, padding: 8, fontSize: 12, marginTop: 6 }}>
      <b>🔧 Tool-call trace</b>
      {events.map((e, i) => (
        <div key={i} style={{ borderTop: '1px solid #334155', paddingTop: 4, marginTop: 4 }}>
          {e.type === 'reasoning' && <div>💭 {String(e.data)}</div>}
          {e.type === 'tool_start' && <div>▶ <code>{e.data.tool}</code> <code>{JSON.stringify(e.data.input)}</code></div>}
          {e.type === 'tool_end' && <div>✔ <code>{e.data.tool}</code>: {String(e.data.output).slice(0, 300)}</div>}
          {e.type === 'cached' && <div>⚡ served from cache</div>}
        </div>
      ))}
    </div>
  );
}
