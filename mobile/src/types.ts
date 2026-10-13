/** Shared types, mirroring the server's API responses. */

export interface Watch {
  id: number;
  label: string;
  store_pattern: string | null;
  bag_pattern: string | null;
  max_price: number | null;
  latitude: number;
  longitude: number;
  radius_km: number;
  enabled: boolean;
  notify_on_increase: boolean;
  /** False until the server has completed one poll; no alerts fire before then. */
  baselined: boolean;
  created_at: string;
  tracked_items: number;
  items_in_stock: number;
}

export interface WatchInput {
  label?: string;
  store_pattern?: string | null;
  bag_pattern?: string | null;
  max_price?: number | null;
  latitude: number;
  longitude: number;
  radius_km?: number;
  notify_on_increase?: boolean;
  enabled?: boolean;
}

export interface PreviewItem {
  item_id: string;
  store_name: string;
  display_name: string;
  quantity: number;
  price: string;
  currency: string | null;
  distance_m: number | null;
  pickup_end: string | null;
  category: string | null;
}

export interface AlertRecord {
  id: number;
  watch_id: number | null;
  watch_label: string | null;
  item_id: string | null;
  title: string;
  body: string;
  devices_ok: number;
  devices_err: number;
  created_at: string;
}

export interface ServerStatus {
  version: string;
  account: string | null;
  logged_in: boolean;
  poll_interval_seconds: number;
  watches: number;
  devices: number;
  last_run: {
    at: string | null;
    items_seen: number;
    matched: number;
    alerts: number;
    errors: number;
    blocked: boolean;
    note: string | null;
  } | null;
  blocked_in_last_24h: number;
}

/** What the pairing QR encodes. `v` lets us change the format later. */
export interface PairingPayload {
  url: string;
  token: string;
  v: number;
}

export interface Connection {
  url: string;
  token: string;
}
