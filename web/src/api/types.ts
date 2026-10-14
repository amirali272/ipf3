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

// ---------------------------------------------------------------- VPN
export type VpnProtocol = "vless" | "vmess" | "trojan" | "shadowsocks";
export type VpnNetwork = "tcp" | "ws" | "grpc" | "httpupgrade" | "xhttp";
export type VpnSecurity = "none" | "tls" | "reality";
export type VpnStatus = "active" | "expired" | "limited" | "disabled";

export interface InboundSettings {
  path: string;
  host: string;
  service_name: string;
  xhttp_mode: "auto" | "packet-up" | "stream-up" | "stream-one";
  flow: "" | "xtls-rprx-vision";
  ss_method: string;
  ss_server_password: string;
  sni: string;
  alpn: string[];
  fingerprint: string;
  cert_pem: string;
  key_pem: string;
  cert_file: string;
  key_file: string;
  target: string;
  server_names: string[];
  private_key: string;
  public_key: string;
  short_ids: string[];
  spider_x: string;
}

export interface Inbound {
  id: number;
  agent_id: string;
  agent_name: string | null;
  remark: string;
  protocol: VpnProtocol;
  port: number;
  listen: string;
  network: VpnNetwork;
  security: VpnSecurity;
  address: string;
  settings: InboundSettings;
  enabled: boolean;
  created_at: string;
  tag: string;
  users: number;
  up: number;
  down: number;
  online: number;
}

export interface VpnUser {
  id: number;
  username: string;
  status: VpnStatus;
  data_limit: number;
  used_up: number;
  used_down: number;
  used: number;
  lifetime_used: number;
  expire_at: string | null;
  enabled: boolean;
  inbound_ids: number[] | null;
  note: string;
  created_at: string;
  last_online_at: string | null;
  online: boolean;
  online_ips: number;
  sub_token: string;
  sub_url: string;
}

export interface VpnNode {
  agent_id: string;
  name: string;
  online: boolean;
  remote_addr: string | null;
  xray_installed: boolean;
  xray_version: string | null;
  running: boolean;
  error: string | null;
  in_sync: boolean;
  applied_at: string | null;
  inbounds: number;
  online_users: number;
}

export interface VpnOverview {
  users_total: number;
  users_by_status: Record<VpnStatus, number>;
  users_online: number;
  inbounds: number;
  traffic: { today_up: number; today_down: number; month_up: number; month_down: number };
  daily: { day: string; up: number; down: number }[];
  top_users: { id: number; username: string; used: number; data_limit: number }[];
  expiring_soon: { id: number; username: string; expire_at: string }[];
  timezone: string;
}

export interface SubInfo {
  username: string;
  status: VpnStatus;
  used_up: number;
  used_down: number;
  used: number;
  data_limit: number;
  expire_at: string | null;
  online: boolean;
  sub_url: string;
  links: string[];
  connections: Connection[];
  apps: { app: string; version: string; last_at: string }[];
  last_online_at: string | null;
}

export interface Connection {
  ip: string;
  node: string;
  last_seen: string;
}

export interface UserApp {
  app: string;
  version: string;
  user_agent: string;
  last_ip: string;
  first_at: string;
  last_at: string;
  fetches: number;
}

export interface UserActivity {
  connections: Connection[];
  apps: UserApp[];
  last_online_at: string | null;
}

export interface Outbound {
  id: number;
  remark: string;
  protocol: string;
  address: string;
  port: number | null;
  network: string;
  security: string;
  agent_ids: string[] | null;
  nodes: string[];
  enabled: boolean;
  up: number;
  down: number;
  rules: number;
  created_at: string;
}

export interface OutboundDetail extends Outbound {
  link: string;
  config: Record<string, unknown>;
}

export type RuleAction = "direct" | "block" | "outbound";

export interface RoutingRule {
  id: number;
  position: number;
  remark: string;
  action: RuleAction;
  outbound_id: number | null;
  outbound: string | null;
  inbound_ids: number[];
  user_ids: number[];
  domains: string[];
  ips: string[];
  port: string;
  network: "" | "tcp" | "udp" | "tcp,udp";
  protocols: ("http" | "tls" | "quic" | "bittorrent")[];
  enabled: boolean;
}

export interface WgInbound {
  agent_id: string;
  agent_name: string;
  online: boolean;
  remark: string;
  listen_port: number;
  network: string;
  address: string;
  dns: string;
  mtu: number;
  persistent_keepalive: number;
  egress_iface: string;
  public_key: string;
  enabled: boolean;
  created_at: string;
  peers: number;
  online_peers: number;
  up: number;
  down: number;
  running: boolean;
  error: string | null;
  in_sync: boolean;
  applied_at: string | null;
}

export interface WgPeer {
  id: number;
  agent_id: string;
  user_id: number;
  username: string;
  address: string;
  enabled: boolean;
  up: number;
  down: number;
  online: boolean;
  last_handshake_at: string | null;
  created_at: string;
}
