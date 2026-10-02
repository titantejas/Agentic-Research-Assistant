import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function ToolTrace({ events }) {
    if (!events.length)
        return null;
    return (_jsxs("div", { style: { background: '#0f172a', color: '#e2e8f0', borderRadius: 8, padding: 8, fontSize: 12, marginTop: 6 }, children: [_jsx("b", { children: "\uD83D\uDD27 Tool-call trace" }), events.map((e, i) => (_jsxs("div", { style: { borderTop: '1px solid #334155', paddingTop: 4, marginTop: 4 }, children: [e.type === 'reasoning' && _jsxs("div", { children: ["\uD83D\uDCAD ", String(e.data)] }), e.type === 'tool_start' && _jsxs("div", { children: ["\u25B6 ", _jsx("code", { children: e.data.tool }), " ", _jsx("code", { children: JSON.stringify(e.data.input) })] }), e.type === 'tool_end' && _jsxs("div", { children: ["\u2714 ", _jsx("code", { children: e.data.tool }), ": ", String(e.data.output).slice(0, 300)] }), e.type === 'cached' && _jsx("div", { children: "\u26A1 served from cache" })] }, i)))] }));
}
