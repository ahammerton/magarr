export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface Initialize {
  appName: string;
  version: string;
  apiKey: string;
}

let apiKey = '';

export function setApiKey(key: string): void {
  apiKey = key;
}

export function getApiKey(): string {
  return apiKey;
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { message?: unknown };
    if (typeof body.message === 'string' && body.message) return body.message;
  } catch {
    // Not JSON; use the fallback.
  }
  return fallback;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers = new Headers({ Accept: 'application/json' });
  if (apiKey) headers.set('X-Api-Key', apiKey);
  if (body !== undefined) headers.set('Content-Type', 'application/json');

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const fallback = `${method} ${path} → ${response.status}`;
    throw new ApiError(response.status, await errorMessage(response, fallback));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Fetches an API image (with the key in a header, not the URL) as a blob. */
export async function apiBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch(path, { headers: apiKey ? { 'X-Api-Key': apiKey } : {}, signal });
  if (!response.ok) throw new ApiError(response.status, `GET ${path} → ${response.status}`);
  return response.blob();
}

/** POSTs a file as the raw request body (e.g. a backup zip). */
export async function apiUpload<T>(path: string, file: Blob, contentType: string): Promise<T> {
  const headers = new Headers({ Accept: 'application/json', 'Content-Type': contentType });
  if (apiKey) headers.set('X-Api-Key', apiKey);
  const response = await fetch(path, { method: 'POST', headers, body: file });
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response, `POST ${path} → ${response.status}`));
  }
  return (await response.json()) as T;
}

/** Downloads an API file (sent with the key in a header) and saves it as ``filename``. */
export async function saveApiFile(path: string, filename: string): Promise<void> {
  const url = URL.createObjectURL(await apiBlob(path));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const apiGet = <T>(path: string) => request<T>('GET', path);
export const apiPost = <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {});
export const apiPut = <T>(path: string, body: unknown) => request<T>('PUT', path, body);
export const apiPatch = <T>(path: string, body: unknown) => request<T>('PATCH', path, body);
export const apiDelete = (path: string) => request<void>('DELETE', path);

export async function initialize(): Promise<Initialize> {
  const data = await apiGet<Initialize>('/initialize.json');
  setApiKey(data.apiKey);
  return data;
}
