import { useCallback, useEffect, useRef, useState } from "react";
import {
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { FormInstance } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  createRule,
  deleteRule,
  listEvents,
  listMetrics,
  listRules,
  testRule,
  updateRule,
  type AlertCondition,
  type AlertEvent,
  type AlertRule,
  type AlertRuleBody,
  type AlertScope,
  type MetricInfo,
} from "../api/alerts";
import { listStocks } from "../api/stocks";
import type { Stock } from "../types/domain";

const { Paragraph, Text } = Typography;

const SCOPE_LABEL: Record<AlertScope, string> = {
  realtime: "实时行情",
  chip: "筹码指标",
  pattern: "筹码形态",
};

const OP_LABEL: Record<string, string> = {
  gt: "大于",
  lt: "小于",
  gte: "大于等于",
  lte: "小于等于",
  cross_above: "上穿",
  cross_below: "下穿",
  eq: "等于",
  ne: "不等于",
};

const STATUS_COLOR: Record<string, string> = {
  sent: "green",
  failed: "red",
  pending: "processing",
  skipped: "default",
};

const STATUS_LABEL: Record<string, string> = {
  sent: "已发送",
  failed: "发送失败",
  pending: "待发送",
  skipped: "已跳过",
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

/** 条件数组 → 中文描述（后端 describe_rule 的前端镜像，仅用于表格展示） */
function describeConditions(conds: AlertCondition[], metrics: MetricInfo[]): string {
  return conds
    .map((c) => {
      const m = metrics.find((x) => x.scope === c.scope && x.metric === c.metric);
      const label = m?.label ?? c.metric;
      const op = OP_LABEL[c.op] ?? c.op;
      const value =
        m && m.options.length > 0
          ? m.options.find((o) => o.value === c.value)?.label ?? c.value
          : String(c.value);
      return `${label} ${op} ${value}`;
    })
    .join(" 且 ");
}

export default function AlertsPage() {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [metrics, setMetrics] = useState<MetricInfo[]>([]);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [editing, setEditing] = useState<AlertRule | "new" | null>(null);
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<AlertEvent | null>(null);
  const [form] = Form.useForm<AlertRuleBody>();

  const loadRules = useCallback(async () => {
    try {
      setRules(await listRules());
    } catch (e) {
      message.error(String((e as Error)?.message ?? e));
    }
  }, []);

  const loadEvents = useCallback(async () => {
    try {
      setEvents(await listEvents());
    } catch (e) {
      message.error(String((e as Error)?.message ?? e));
    }
  }, []);

  useEffect(() => {
    listMetrics()
      .then(setMetrics)
      .catch((e) => message.error(String((e as Error)?.message ?? e)));
    listRules()
      .then(setRules)
      .catch((e) => message.error(String((e as Error)?.message ?? e)));
  }, []);

  const openEditor = (rule: AlertRule | "new") => {
    setEditing(rule);
    if (rule === "new") {
      form.setFieldsValue({
        name: "",
        enabled: true,
        secucodes: [],
        conditions: [{ scope: "realtime", metric: "pct_change", op: "gte", value: 5 }],
        cooldown_minutes: 10,
        webhook_url: null,
      });
    } else {
      form.setFieldsValue({
        name: rule.name,
        enabled: rule.enabled,
        secucodes: rule.secucodes,
        conditions: rule.conditions,
        cooldown_minutes: rule.cooldown_minutes,
        webhook_url: rule.webhook_url,
      });
    }
  };

  const submit = async () => {
    let body: AlertRuleBody;
    try {
      body = await form.validateFields();
    } catch {
      return; // 校验失败：表单已标红，保持弹窗打开（防 onOk unhandled rejection）
    }
    setSaving(true);
    try {
      if (editing === "new") {
        await createRule(body);
        message.success("规则已创建");
      } else if (editing) {
        await updateRule(editing.id, body);
        message.success("规则已保存");
      }
      setEditing(null);
      await loadRules();
    } catch (e) {
      message.error(String((e as Error)?.message ?? e));
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (rule: AlertRule, enabled: boolean) => {
    // 乐观更新：先改 UI，PUT 失败再回滚刷新
    setRules((rs) => rs.map((r) => (r.id === rule.id ? { ...r, enabled } : r)));
    try {
      await updateRule(rule.id, { ...rule, enabled });
    } catch (e) {
      message.error(String((e as Error)?.message ?? e));
      loadRules();
    }
  };

  const onTest = async (rule: AlertRule) => {
    const key = "alert-test";
    message.loading({ content: "发送测试消息…", key, duration: 0 });
    try {
      const r = await testRule(rule.id);
      message.success({ content: "测试消息已发送", key });
      Modal.info({ title: "发送内容预览", content: <pre style={{ maxHeight: 320, overflow: "auto" }}>{r.message}</pre> });
    } catch (e) {
      message.error({ content: String((e as Error)?.message ?? e), key });
    }
  };

  const onDelete = async (rule: AlertRule) => {
    try {
      await deleteRule(rule.id);
      message.success("规则已删除");
      loadRules();
    } catch (e) {
      message.error(String((e as Error)?.message ?? e));
    }
  };

  const ruleColumns: ColumnsType<AlertRule> = [
    { title: "名称", dataIndex: "name" },
    {
      title: "股票",
      dataIndex: "secucodes",
      width: 90,
      align: "center",
      render: (v: string[]) => (
        <Tooltip title={v.join("、")}>
          <span>{v.length} 只</span>
        </Tooltip>
      ),
    },
    {
      title: "条件",
      dataIndex: "conditions",
      render: (v: AlertCondition[]) =>
        metrics.length ? describeConditions(v, metrics) : JSON.stringify(v),
    },
    {
      title: "冷却(分)",
      dataIndex: "cooldown_minutes",
      width: 90,
      align: "right",
    },
    {
      title: "启用",
      dataIndex: "enabled",
      width: 80,
      align: "center",
      render: (_: unknown, rule: AlertRule) => (
        <Switch
          checked={rule.enabled}
          onChange={(v) => toggleEnabled(rule, v)}
        />
      ),
    },
    {
      title: "操作",
      width: 200,
      render: (_: unknown, rule: AlertRule) => (
        <Space>
          <Button size="small" onClick={() => openEditor(rule)}>
            编辑
          </Button>
          <Button size="small" onClick={() => onTest(rule)}>
            测试
          </Button>
          <Popconfirm title="删除规则及其全部触发历史？" onConfirm={() => onDelete(rule)}>
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const eventColumns: ColumnsType<AlertEvent> = [
    {
      title: "时间",
      dataIndex: "triggered_at",
      width: 170,
      render: (v: string) => fmtTime(v),
    },
    { title: "规则", dataIndex: "rule_name" },
    {
      title: "股票",
      render: (_: unknown, e: AlertEvent) =>
        e.stock_name ? `${e.stock_name}（${e.secucode}）` : e.secucode,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (v: string, e: AlertEvent) => (
        <Tooltip title={e.detail || undefined}>
          <Tag color={STATUS_COLOR[v] ?? "default"}>{STATUS_LABEL[v] ?? v}</Tag>
        </Tooltip>
      ),
    },
    {
      title: "条件",
      dataIndex: "message",
      ellipsis: true,
      render: (v: string, e: AlertEvent) => (
        <a onClick={() => setDetail(e)}>
          {/* 按行前缀提取，避免依赖模板行号 */}
          {v
            .split("\n")
            .find((l) => l.startsWith("> **条件**："))
            ?.replace("> **条件**：", "")
            .replace(/\*\*/g, "") ?? v.slice(0, 60)}
        </a>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Tabs
        defaultActiveKey="rules"
        items={[
          {
            key: "rules",
            label: "规则",
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <Button type="primary" onClick={() => openEditor("new")}>
                  新建规则
                </Button>
                <Table
                  size="small"
                  rowKey="id"
                  columns={ruleColumns}
                  dataSource={rules}
                  pagination={{ pageSize: 20 }}
                />
              </Space>
            ),
          },
          {
            key: "events",
            label: "触发历史",
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <Button onClick={loadEvents}>刷新</Button>
                <Table
                  size="small"
                  rowKey="id"
                  columns={eventColumns}
                  dataSource={events}
                  pagination={{ pageSize: 20 }}
                />
              </Space>
            ),
          },
        ]}
        onChange={(key) => {
          if (key === "events") loadEvents();
        }}
      />

      <Modal
        title={editing === "new" ? "新建规则" : "编辑规则"}
        open={editing !== null}
        onOk={submit}
        onCancel={() => setEditing(null)}
        confirmLoading={saving}
        width={760}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="规则名称"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input placeholder="如：涨幅超5%" maxLength={64} />
          </Form.Item>
          <Form.Item
            name="secucodes"
            label="监控股票"
            rules={[{ required: true, message: "请选择至少一只股票" }]}
          >
            <StockPicker initial={editing && editing !== "new" ? editing.secucodes : []} />
          </Form.Item>
          <Form.Item label="触发条件（全部满足时触发）" required>
            <ConditionBuilder metrics={metrics} form={form} />
          </Form.Item>
          <Space size="large">
            <Form.Item
              name="cooldown_minutes"
              label="冷却（分钟）"
              initialValue={10}
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={1440} />
            </Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
              <Switch />
            </Form.Item>
          </Space>
          <Form.Item name="webhook_url" label="Webhook（企业微信机器人）">
            <Input placeholder="留空用全局配置（CHIPSCOPE_ALERT_WEBHOOK_URL）" maxLength={512} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={detail ? `${detail.rule_name} · ${detail.stock_name}（${detail.secucode}）` : ""}
        open={detail !== null}
        onClose={() => setDetail(null)}
        width={520}
      >
        {detail && (
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <div>
              <Text type="secondary">触发时间：</Text>
              <Text>{fmtTime(detail.triggered_at)}</Text>
            </div>
            <div>
              <Tag color={STATUS_COLOR[detail.status]}>
                {STATUS_LABEL[detail.status] ?? detail.status}
              </Tag>
              {detail.trade_date && <Tag>交易日 {detail.trade_date}</Tag>}
            </div>
            {detail.detail && (
              <Paragraph type="danger">失败原因：{detail.detail}</Paragraph>
            )}
            <div>
              <Text type="secondary">消息内容</Text>
              <pre style={{ background: "#fafafa", padding: 12, whiteSpace: "pre-wrap" }}>
                {detail.message}
              </pre>
            </div>
            <div>
              <Text type="secondary">指标快照</Text>
              <pre style={{ background: "#fafafa", padding: 12, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(detail.payload, null, 2)}
              </pre>
            </div>
          </Space>
        )}
      </Drawer>
    </Space>
  );
}

/** 股票多选：远程搜索走 GET /api/stocks?q=，已选代码兜底显示。
 * value/onChange 由 Form.Item name="secucodes" 注入，必须转发进 Select，
 * 否则选择结果进不了表单 store（受控组件约定）。 */
function StockPicker({
  value,
  onChange,
  initial,
}: {
  value?: string[];
  onChange?: (v: string[]) => void;
  initial: string[];
}) {
  // 已在规则里的代码直接作为初始选项（Modal destroyOnClose，每次打开重新 mount）
  const [options, setOptions] = useState<{ value: string; label: string }[]>(() =>
    initial.map((c) => ({ value: c, label: c }))
  );
  const [searching, setSearching] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onSearch = (text: string) => {
    if (timer.current) clearTimeout(timer.current);
    if (!text.trim()) return;
    timer.current = setTimeout(async () => {
      setSearching(true);
      try {
        const stocks: Stock[] = await listStocks(text);
        setOptions((prev) => {
          const known = new Map(prev.map((o) => [o.value, o.label]));
          for (const s of stocks) known.set(s.secucode, `${s.name} ${s.secucode}`);
          return [...known.entries()].map(([value, label]) => ({ value, label }));
        });
      } catch {
        message.error("股票搜索失败");
      } finally {
        setSearching(false);
      }
    }, 300);
  };

  return (
    <Select
      mode="multiple"
      showSearch
      loading={searching}
      filterOption={false}
      onSearch={onSearch}
      value={value}
      onChange={onChange}
      options={options}
      placeholder="输入代码/名称搜索，如 600519"
      style={{ width: "100%" }}
    />
  );
}

/** 条件构造器：Form.List 动态行，scope→metric→op 联动，pattern/trend 值用下拉 */
function ConditionBuilder({
  metrics,
  form,
}: {
  metrics: MetricInfo[];
  form: FormInstance<AlertRuleBody>;
}) {
  return (
    <Form.List name="conditions">
      {(fields, { add, remove }) => (
        <>
          {fields.map(({ key, name }) => (
            <Form.Item key={key} noStyle shouldUpdate>
              {(inner: FormInstance) => {
                const getFieldValue = inner.getFieldValue;
                const conds = (getFieldValue("conditions") ?? []) as AlertCondition[];
                const cond = conds[name];
                const scopeMetrics = metrics.filter((m) => m.scope === cond?.scope);
                const metric = scopeMetrics.find((m) => m.metric === cond?.metric);
                const isEnum = (metric?.options.length ?? 0) > 0;
                return (
                  <Space
                    key={key}
                    align="baseline"
                    style={{ display: "flex", marginBottom: 4, flexWrap: "wrap" }}
                  >
                    <Form.Item
                      name={[name, "scope"]}
                      rules={[{ required: true }]}
                      style={{ marginBottom: 8 }}
                    >
                      <Select
                        style={{ width: 110 }}
                        options={Object.entries(SCOPE_LABEL).map(([value, label]) => ({
                          value,
                          label,
                        }))}
                        onChange={(v) =>
                          form.setFieldValue(["conditions", name], {
                            scope: v,
                            metric: undefined,
                            op: undefined,
                            value: undefined,
                          })
                        }
                      />
                    </Form.Item>
                    <Form.Item
                      name={[name, "metric"]}
                      rules={[{ required: true, message: "选指标" }]}
                      style={{ marginBottom: 8 }}
                    >
                      <Select
                        style={{ width: 170 }}
                        showSearch
                        optionFilterProp="label"
                        options={scopeMetrics.map((m) => ({ value: m.metric, label: m.label }))}
                        onChange={(v) =>
                          form.setFieldValue(["conditions", name], {
                            ...cond,
                            metric: v,
                            op: undefined,
                            value: undefined,
                          })
                        }
                      />
                    </Form.Item>
                    <Form.Item
                      name={[name, "op"]}
                      rules={[{ required: true, message: "选操作符" }]}
                      style={{ marginBottom: 8 }}
                    >
                      <Select
                        style={{ width: 120 }}
                        options={(metric?.ops ?? []).map((op) => ({
                          value: op,
                          label: OP_LABEL[op] ?? op,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item
                      name={[name, "value"]}
                      rules={[{ required: true, message: "填阈值" }]}
                      style={{ marginBottom: 8 }}
                    >
                      {isEnum ? (
                        <Select
                          style={{ width: 140 }}
                          options={metric?.options ?? []}
                        />
                      ) : (
                        <InputNumber style={{ width: 140 }} placeholder="阈值" />
                      )}
                    </Form.Item>
                    <Button
                      type="link"
                      danger
                      size="small"
                      disabled={fields.length <= 1}
                      onClick={() => remove(name)}
                    >
                      删除
                    </Button>
                  </Space>
                );
              }}
            </Form.Item>
          ))}
          <Button
            size="small"
            onClick={() =>
              add({ scope: "realtime", metric: "pct_change", op: "gte", value: 5 })
            }
          >
            + 添加条件
          </Button>
        </>
      )}
    </Form.List>
  );
}
