const BASE = "/api";

export async function apiGet<T>(
  path: string,
  params?: Record<string, string>
): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const resp = await fetch(url.toString());
  if (!resp.ok) {
    throw new Error(`API ${path}: ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}
