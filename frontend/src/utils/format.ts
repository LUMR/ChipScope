export function ma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      out.push(null);
      continue;
    }
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    out.push(sum / period);
  }
  return out;
}

export const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

export const fmt = (v: number, digits = 2) =>
  v.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
