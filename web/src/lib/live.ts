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
  rx_pps?: number;
  tx_pps?: number;
}

/** Current consumption reported by an agent every ≈2 s. */
export interface LiveRatePoint {
  t: number;
  rx: number;
  tx: number;
}

export interface LiveState {
  connected: boolean;
  lastTick: number | null;
  agents: { id: string; name: string; online: boolean; last_seen_at: string | null }[];
  alertsFiring: number;
  metrics: Record<string, LiveMetric[]>;
  /** ≈2 s rate history per agent, since the page was opened. */
  rates: Record<string, LiveRatePoint[]>;
  /** ≈2 s per-interface rates of the focused agent. */
  ifaces: LiveIface[];
}

const KEEP_POINTS = 180; // 10 s samples: ~30 min
const KEEP_RATES = 900; // 2 s samples: ~30 min
const KEEP_IFACE = 6000;

/** Subscribes to /api/v1/ws/live. Only real samples reported by agents are shown;
 *  nothing is interpolated or synthesised client-side. */
export function useLive(focusAgent?: string): LiveState {
  const [state, setState] = useState<LiveState>({
    connected: false,
    lastTick: null,
    agents: [],
    alertsFiring: 0,
    metrics: {},
    rates: {},
    ifaces: [],
  });
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
          const rates = { ...s.rates };
          let ifaces = s.ifaces;
          for (const r of (frame.live ?? []) as {
            agent_id: string;
            ts: string;
            rx_bps: number;
            tx_bps: number;
            interfaces: { iface: string; rx_bps: number; tx_bps: number }[] | null;
          }[]) {
            const t = new Date(r.ts).getTime();
            const arr = rates[r.agent_id] ? [...rates[r.agent_id]] : [];
            if (arr.length && arr[arr.length - 1].t >= t) continue; // same report seen in an earlier tick
            arr.push({ t, rx: r.rx_bps, tx: r.tx_bps });
            if (arr.length > KEEP_RATES) arr.splice(0, arr.length - KEEP_RATES);
            rates[r.agent_id] = arr;
            if (r.interfaces && r.agent_id === focusRef.current) {
              ifaces = [...ifaces, ...r.interfaces.map((i) => ({ ...i, agent_id: r.agent_id, ts: r.ts }))];
            }
          }
          if (ifaces.length > KEEP_IFACE) ifaces = ifaces.slice(-KEEP_IFACE);
          return {
            connected: true,
            lastTick: Date.now(),
            agents: frame.agents,
            alertsFiring: frame.alerts_firing,
            metrics,
            rates,
            ifaces,
          };
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

/** Fleet-wide current rate: at each 2 s slot, the sum of every agent's most
 *  recent report (a report older than `maxAgeMs` no longer counts). */
export function fleetRates(rates: Record<string, LiveRatePoint[]>, slotMs = 2000, maxAgeMs = 6000): LiveRatePoint[] {
  const series = Object.values(rates).filter((a) => a.length);
  if (!series.length) return [];
  const slotSet = new Set<number>();
  for (const arr of series) for (const p of arr) slotSet.add(Math.round(p.t / slotMs) * slotMs);
  const slots = [...slotSet].sort((a, b) => a - b);
  const idx = series.map(() => 0);
  return slots.map((t) => {
    let rx = 0;
    let tx = 0;
    series.forEach((arr, k) => {
      while (idx[k] + 1 < arr.length && arr[idx[k] + 1].t <= t + slotMs / 2) idx[k]++;
      const p = arr[idx[k]];
      if (p.t <= t + slotMs / 2 && t - p.t <= maxAgeMs) {
        rx += p.rx;
        tx += p.tx;
      }
    });
    return { t, rx, tx };
  });
}
