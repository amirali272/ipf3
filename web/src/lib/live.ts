import { useEffect, useRef, useState } from "react";

export interface LiveMetric {
  agent_id: string;
  ts: string;
  cpu_percent: number | null;
  mem_percent: number | null;
  load1: number | null;
  rx_bps: number | null;
  tx_bps: number | null;
  tcp_established: number | null;
}

export interface LiveIface {
  agent_id: string;
  ts: string;
  iface: string;
  rx_bps: number;
  tx_bps: number;
  rx_pps: number;
  tx_pps: number;
}

export interface LiveState {
  connected: boolean;
  agents: { id: string; name: string; online: boolean; last_seen_at: string | null }[];
  alertsFiring: number;
  metrics: Record<string, LiveMetric[]>;
  ifaces: LiveIface[];
}

const KEEP_POINTS = 180; // ~30 min at a 10 s collection interval
const KEEP_IFACE = 3000;

/** Subscribes to /api/v1/ws/live. Only real samples reported by agents are shown;
 *  nothing is interpolated or synthesised client-side. */
export function useLive(focusAgent?: string): LiveState {
  const [state, setState] = useState<LiveState>({ connected: false, agents: [], alertsFiring: 0, metrics: {}, ifaces: [] });
  const wsRef = useRef<WebSocket | null>(null);
  const focusRef = useRef(focusAgent);
  focusRef.current = focusAgent;

  useEffect(() => {
    let closed = false;
    let retry = 1000;
    let timer: number | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/v1/ws/live`);
      wsRef.current = ws;
      ws.onopen = () => {
        retry = 1000;
        setState((s) => ({ ...s, connected: true }));
        ws.send(JSON.stringify({ focus: focusRef.current ?? null }));
      };
      ws.onmessage = (ev) => {
        const frame = JSON.parse(ev.data);
        if (frame.type !== "tick") return;
        setState((s) => {
          const metrics = { ...s.metrics };
          for (const m of frame.metrics as LiveMetric[]) {
            const arr = metrics[m.agent_id] ? [...metrics[m.agent_id]] : [];
            arr.push(m);
            if (arr.length > KEEP_POINTS) arr.splice(0, arr.length - KEEP_POINTS);
            metrics[m.agent_id] = arr;
          }
          let ifaces = frame.interfaces.length ? [...s.ifaces, ...frame.interfaces] : s.ifaces;
          if (ifaces.length > KEEP_IFACE) ifaces = ifaces.slice(-KEEP_IFACE);
          return { connected: true, agents: frame.agents, alertsFiring: frame.alerts_firing, metrics, ifaces };
        });
      };
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!closed) {
          timer = window.setTimeout(connect, retry);
          retry = Math.min(retry * 2, 30000);
        }
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      wsRef.current?.close();
    };
  }, []);

  useEffect(() => {
    setState((s) => ({ ...s, ifaces: [] }));
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ focus: focusAgent ?? null }));
  }, [focusAgent]);

  return state;
}
