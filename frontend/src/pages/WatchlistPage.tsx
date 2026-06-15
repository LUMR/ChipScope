import {
  AutoComplete,
  Button,
  Input,
  Popconfirm,
  Space,
  Spin,
  Table,
  Typography,
} from "antd";
import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useState } from "react";
import { useStockSearch } from "../hooks/useStockSearch";
import { useWatchlist } from "../hooks/useWatchlist";
import { useQuote } from "../hooks/useRealtimeQuotes";
import type { WatchlistItem } from "../types/domain";

const { Title, Text } = Typography;

export default function WatchlistPage() {
  const { items, loading, add, remove, reorder } = useWatchlist();
  const [text, setText] = useState("");
  const opts = useStockSearch(text);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  );

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const ids = items.map((i) => i.secucode);
    const from = ids.indexOf(active.id as string);
    const to = ids.indexOf(over.id as string);
    reorder(arrayMove(ids, from, to));
  };

  return (
    <div style={{ maxWidth: 900 }}>
      <Title level={4} style={{ marginTop: 0 }}>
        自选管理
      </Title>
      <AutoComplete
        style={{ width: 360, marginBottom: 16 }}
        options={opts}
        value={text}
        onChange={setText}
        onSelect={async (val: string) => {
          setText("");
          await add(val);
        }}
      >
        <Input.Search placeholder="搜索股票代码/名称添加" />
      </AutoComplete>

      {loading ? (
        <Spin />
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={onDragEnd}
        >
          <SortableContext
            items={items.map((i) => i.secucode)}
            strategy={verticalListSortingStrategy}
          >
            <Table<WatchlistItem>
              rowKey="secucode"
              dataSource={items}
              pagination={false}
              components={{ body: { row: SortableRow } }}
              columns={[
                {
                  title: "代码",
                  dataIndex: "code",
                  width: 90,
                  render: (_: unknown, r: WatchlistItem) => (
                    <Text strong>{r.code}</Text>
                  ),
                },
                { title: "名称", dataIndex: "name" },
                {
                  title: "行业",
                  dataIndex: "industry",
                  width: 120,
                  render: (v: string | null) => (
                    <Text type="secondary">{v ?? "—"}</Text>
                  ),
                },
                {
                  title: "现价",
                  width: 90,
                  render: (_: unknown, r: WatchlistItem) => <PriceCell secucode={r.secucode} />,
                },
                {
                  title: "操作",
                  width: 80,
                  render: (_: unknown, r: WatchlistItem) => (
                    <Popconfirm
                      title={`移出 ${r.name}？`}
                      onConfirm={() => remove(r.secucode)}
                      okText="移出"
                      cancelText="取消"
                    >
                      <Button type="link" danger size="small">
                        删除
                      </Button>
                    </Popconfirm>
                  ),
                },
              ]}
            />
          </SortableContext>
        </DndContext>
      )}
      <Space style={{ marginTop: 16 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          拖动行调整顺序 · 增删即时同步到行情监控
        </Text>
      </Space>
    </div>
  );
}

function PriceCell({ secucode }: { secucode: string }) {
  const quote = useQuote(secucode);
  if (!quote || quote.price == null) {
    return <Text type="secondary">—</Text>;
  }
  return (
    <Text style={{ fontFamily: "ui-monospace, monospace" }}>
      {quote.price.toFixed(2)}
    </Text>
  );
}

function SortableRow(props: React.HTMLAttributes<HTMLTableRowElement> & { "data-row-key"?: string }) {
  const id = props["data-row-key"] as string | undefined;
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: id ?? "", disabled: !id });
  return (
    <tr
      {...props}
      ref={setNodeRef}
      style={{
        ...props.style,
        transform: CSS.Transform.toString(transform) ?? undefined,
        transition,
        cursor: isDragging ? "grabbing" : "pointer",
        background: isDragging ? "#f0f5ff" : props.style?.background,
      }}
      {...attributes}
      {...listeners}
    />
  );
}
