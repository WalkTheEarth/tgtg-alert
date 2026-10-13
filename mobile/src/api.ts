/**
 * Client for the self-hosted server.
 *
 * Every call carries the pairing token. Errors are turned into a single
 * `ApiError` carrying the server's own message where there is one, because a
 * self-hoster debugging their own box needs the real reason ("blocked, retry in
 * 43 min") rather than "request failed".
 */

import type {
  AlertRecord,
  Connection,
  PreviewItem,
  ServerStatus,
  Watch,
  WatchInput,
} from './types';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export class ApiClient {
  private connection: Connection;

  constructor(connection: Connection) {
    this.connection = {
      url: connection.url.replace(/\/+$/, ''),
      token: connection.token,
    };
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController();
    // Without a timeout a wrong URL hangs on a spinner forever, which is the
    // most common setup mistake.
    const timeout = setTimeout(() => controller.abort(), 20000);

    let response: Response;
    try {
      response = await fetch(`${this.connection.url}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.connection.token}`,
          ...(init.headers ?? {}),
        },
      });
    } catch (error) {
      clearTimeout(timeout);
      if ((error as Error)?.name === 'AbortError') {
        throw new ApiError('The server did not respond in time.', 0);
      }
      throw new ApiError(
        `Could not reach ${this.connection.url}. Check the address and that the server is running.`,
        0,
      );
    }
    clearTimeout(timeout);

    if (response.status === 204) {
      return undefined as T;
    }

    const text = await response.text();
    let body: any = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }

    if (!response.ok) {
      const detail =
        (body && (body.detail || body.message)) ||
        `Request failed (${response.status})`;
      throw new ApiError(String(detail), response.status);
    }

    return body as T;
  }

  // -- status -----------------------------------------------------------

  status(): Promise<ServerStatus> {
    return this.request<ServerStatus>('/api/status');
  }

  // -- watches ----------------------------------------------------------

  listWatches(): Promise<Watch[]> {
    return this.request<Watch[]>('/api/watches');
  }

  createWatch(input: WatchInput): Promise<Watch> {
    return this.request<Watch>('/api/watches', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  }

  updateWatch(id: number, input: Partial<WatchInput>): Promise<Watch> {
    return this.request<Watch>(`/api/watches/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  }

  deleteWatch(id: number): Promise<void> {
    return this.request<void>(`/api/watches/${id}`, { method: 'DELETE' });
  }

  rebaselineWatch(id: number): Promise<{ ok: boolean }> {
    return this.request<{ ok: boolean }>(`/api/watches/${id}/rebaseline`, {
      method: 'POST',
    });
  }

  // -- discovery --------------------------------------------------------

  preview(params: {
    latitude: number;
    longitude: number;
    radius_km?: number;
    query?: string;
    limit?: number;
  }): Promise<{ count: number; items: PreviewItem[] }> {
    return this.request('/api/preview', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  }

  // -- devices & activity -----------------------------------------------

  registerDevice(expoPushToken: string, platform: string, label: string) {
    return this.request<{ id: number }>('/api/devices', {
      method: 'POST',
      body: JSON.stringify({
        expo_push_token: expoPushToken,
        platform,
        label,
      }),
    });
  }

  listAlerts(limit = 50): Promise<AlertRecord[]> {
    return this.request<AlertRecord[]>(`/api/alerts?limit=${limit}`);
  }

  testNotify(): Promise<{ sent: number; errors: number; messages: string[] }> {
    return this.request('/api/test-notify', { method: 'POST' });
  }

  /** Cheap reachability probe used by the setup screen. */
  async ping(): Promise<boolean> {
    try {
      await this.request('/api/status');
      return true;
    } catch {
      return false;
    }
  }
}
