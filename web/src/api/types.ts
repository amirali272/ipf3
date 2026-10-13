export type Role = "admin" | "operator" | "viewer";
export type JobType = "iperf3" | "ping" | "traceroute" | "mtr" | "dns";
export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "expired";
export type Severity = "info" | "warning" | "critical";

export interface User {
  id: number;
  username: string;
  email: string | null;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  locked_until: string | null;
}

export interface LatestMetrics {
  ts: string;
  cpu_percent: number | null;
  mem_percent: number | null;
  disk_percent: number | null;
  load1: number | null;
  load5: number | null;
  load15: number | null;
  rx_bps: number | null;
  tx_bps: number | null;
  tcp_established: number | null;
  uptime_seconds: number | null;
}

export interface Agent {
  id: string;
  name: string;
  hostname: string;
  os_name: string;
  kernel: string;
  agent_version: string;
  cpu_count: number | null;
  capabilities: { tools?: Record<string, boolean>; arch?: string };
  tags: string[];
  remote_addr: string | null;
  disabled: boolean;
  created_at: string;
  last_seen_at: string | null;
  online: boolean;
  latest: LatestMetrics | null;
}

export interface EnrollmentToken {
  id: number;
  note: string;
  created_at: string;
  expires_at: string;
  used_at: string | null;
  agent_id: string | null;
  token?: string | null;
}

export interface MetricPoint {
  t: string;
  cpu_percent: number | null;
  mem_percent: number | null;
  swap_percent: number | null;
  disk_percent: number | null;
  load1: number | null;
  load5: number | null;
  load15: number | null;
  rx_bps: number | null;
  tx_bps: number | null;
  rx_bps_max: number | null;
  tx_bps_max: number | null;
  tcp_established: number | null;
  tcp_time_wait: number | null;
  udp_sockets: number | null;
  tcp_retrans: number | null;
}

export interface IfacePoint {
  t: string;
  iface: string;
  rx_bps: number;
  tx_bps: number;
  rx_bps_max: number;
  tx_bps_max: number;
  rx_pps: number;
  tx_pps: number;
  errors: number;
  drops: number;
}

export interface Series<P> {
  bucket: number;
  from: string;
  to: string;
  points: P[];
}

export interface Inventory {
  updated_at: string | null;
  interfaces: {
    name: string;
    state?: string;
    mtu?: number;
    mac?: string;
    speed_mbps?: number | null;
    duplex?: string | null;
    addresses: string[];
    flags?: string[];
  }[];
  routes: Route[];
  routes6: Route[];
  connections: { proto: string; state: string; recv_q: number | null; send_q: number | null; local: string; peer: string }[];
  dns: { nameservers?: string[]; search?: string[]; options?: string[]; upstream_nameservers?: string[]; resolver?: string };
  system: Record<string, unknown>;
}

export interface Route {
  dst: string | null;
  gateway: string | null;
  dev: string | null;
  protocol: string | null;
  scope: string | null;
  metric: number | null;
  prefsrc: string | null;
  table: string | null;
  type: string | null;
}

export interface Job {
  id: string;
  agent_id: string;
  agent_name: string | null;
  type: JobType;
  params: Record<string, unknown>;
  target: string;
  status: JobStatus;
  created_by: number | null;
  schedule_id: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  bps: number | null;
  rtt_avg_ms: number | null;
  loss_percent: number | null;
  jitter_ms: number | null;
  retransmits: number | null;
}

export interface JobDetail extends Job {
  result: Record<string, any> | null;
  raw: string | null;
}

export interface Schedule {
  id: number;
  name: string;
  agent_id: string;
  type: JobType;
  params: Record<string, unknown>;
  interval_seconds: number;
  enabled: boolean;
  created_at: string;
  last_run_at: string | null;
}

export interface AlertRule {
  id: number;
  name: string;
  metric: string;
  operator: string;
  threshold: number;
  for_seconds: number;
  agent_id: string | null;
  iface: string | null;
  target: string | null;
  severity: Severity;
  enabled: boolean;
  webhook_url: string | null;
  email_to: string | null;
  created_at: string;
}

export interface AlertEvent {
  id: number;
  rule_id: number;
  rule_name: string | null;
  metric: string | null;
  agent_id: string | null;
  agent_name: string | null;
  state: "firing" | "resolved";
  severity: Severity;
  value: number | null;
  message: string;
  started_at: string;
  resolved_at: string | null;
  acknowledged_by: number | null;
  acknowledged_at: string | null;
}

export interface Overview {
  agents_total: number;
  agents_online: number;
  agents_disabled: number;
  alerts_firing: Partial<Record<Severity, number>>;
  jobs_24h: Partial<Record<JobStatus, number>>;
  fleet_rx_bps: number;
  fleet_tx_bps: number;
}

export interface TestSeriesPoint {
  t: string;
  count: number;
  bps_avg: number | null;
  bps_min: number | null;
  bps_max: number | null;
  rtt_avg_ms: number | null;
  rtt_max_ms: number | null;
  loss_percent: number | null;
  jitter_ms: number | null;
  retransmits: number | null;
}

export interface TestSeries extends Series<TestSeriesPoint> {
  summary: {
    completed: number;
    failed: number;
    bps_avg: number | null;
    rtt_avg_ms: number | null;
    rtt_p95_ms: number | null;
    loss_percent: number | null;
    jitter_ms: number | null;
  };
}

export interface AuditEntry {
  id: number;
  ts: string;
  user_id: number | null;
  username: string;
  action: string;
  target: string;
  details: Record<string, unknown>;
  ip: string | null;
}

export interface UsageAgent {
  agent_id: string;
  name: string;
  today_rx: number;
  today_tx: number;
  month_rx: number;
  month_tx: number;
  period_rx: number;
  period_tx: number;
}

export interface Usage {
  timezone: string;
  today: string;
  month_start: string;
  days: number;
  fleet: Omit<UsageAgent, "agent_id" | "name">;
  agents: UsageAgent[];
  daily: { day: string; rx_bytes: number; tx_bytes: number }[];
}

export interface SystemStatus {
  version: string;
  api: boolean;
  database: boolean;
  worker: boolean;
  cpu_percent: number | null;
  mem_percent: number | null;
  disk_percent: number | null;
  usage_timezone: string;
}

export interface FleetPoint {
  t: string;
  rx_bps: number | null;
  tx_bps: number | null;
  rx_bytes: number | null;
  tx_bytes: number | null;
}
