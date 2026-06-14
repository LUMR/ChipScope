import { Slider } from "antd";
import { useMemo } from "react";

export default function DateSlider({
  dates,
  value,
  onChange,
}: {
  dates: string[];
  value: number;
  onChange: (idx: number) => void;
}) {
  const marks = useMemo(() => {
    if (dates.length === 0) return {};
    return { 0: dates[0], [dates.length - 1]: dates[dates.length - 1] };
  }, [dates]);

  if (dates.length === 0) return null;

  return (
    <div style={{ padding: "8px 16px" }}>
      <Slider
        min={0}
        max={dates.length - 1}
        value={value}
        onChange={onChange}
        marks={marks}
        tooltip={{ formatter: (i) => dates[i] ?? "" }}
      />
    </div>
  );
}
