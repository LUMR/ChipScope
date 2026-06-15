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

export async function apiPost<T>(
  path: string,
  body?: unknown
): Promise<T> {
  const resp = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    throw new Error(`API POST ${path}: ${resp.status}`);
  }
  return resp.status === 204 ? (undefined as T) : (resp.json() as Promise<T>);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const resp = await fetch(BASE + path, { method: "DELETE" });
  if (!resp.ok) {
    throw new Error(`API DELETE ${path}: ${resp.status}`);
  }
  return resp.status === 204 ? (undefined as T) : (resp.json() as Promise<T>);
}

export async function apiPut<T>(
  path: string,
  body?: unknown
): Promise<T> {
  const resp = await fetch(BASE + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    throw new Error(`API PUT ${path}: ${resp.status}`);
  }
  return resp.status === 204 ? (undefined as T) : (resp.json() as Promise<T>);
}
