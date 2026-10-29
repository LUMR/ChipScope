import { apiDelete, apiGet, apiPost, apiPut } from "./client";

export type AlertScope = "realtime" | "chip" | "pattern";

export interface AlertCondition {
  scope: AlertScope;
  metric: string;
  op: string;
  value: number | string;
}

export interface AlertRule {
  id: number;
  name: string;
  enabled: boolean;
  secucodes: string[];
  conditions: AlertCondition[];
  cooldown_minutes: number;
  webhook_url: string | null;
  created_at: string;
  updated_at: string;
}

/** 新建/更新请求体（无 id 与时间戳） */
export type AlertRuleBody = Omit<AlertRule, "id" | "created_at" | "updated_at">;

export interface AlertEvent {
  id: number;
  rule_id: number;
  rule_name: string;
  stock_name: string;
  secucode: string;
  triggered_at: string;
  trade_date: string | null;
  status: "pending" | "sent" | "failed" | "skipped";
  payload: Record<string, unknown>;
  message: string;
  detail: string | null;
}

export interface MetricOption {
  value: string;
  label: string;
}

export interface MetricInfo {
  scope: AlertScope;
  metric: string;
  label: string;
  ops: string[];
  /** 枚举取值（pattern/trend）；数值 metric 为空数组 */
  options: MetricOption[];
}

export const listMetrics = (): Promise<MetricInfo[]> =>
  apiGet<MetricInfo[]>("/alerts/metrics");

export const listRules = (): Promise<AlertRule[]> =>
  apiGet<AlertRule[]>("/alerts/rules");

export const createRule = (body: AlertRuleBody): Promise<AlertRule> =>
  apiPost<AlertRule>("/alerts/rules", body);

export const updateRule = (
  id: number,
  body: AlertRuleBody
): Promise<AlertRule> => apiPut<AlertRule>(`/alerts/rules/${id}`, body);

export const deleteRule = (id: number): Promise<void> =>
  apiDelete<void>(`/alerts/rules/${id}`);

export const listEvents = (
  params?: Record<string, string>
): Promise<AlertEvent[]> => apiGet<AlertEvent[]>("/alerts/events", params);

export interface TestResult {
  ok: boolean;
  message: string;
}

export const testRule = (id: number): Promise<TestResult> =>
  apiPost<TestResult>(`/alerts/rules/${id}/test`);
