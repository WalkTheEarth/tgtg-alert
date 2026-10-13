/**
 * Pairing credentials, in the OS keychain.
 *
 * The API token is a bearer credential for the user's own server -- anyone who
 * reads it can edit their watches and push to their phone. SecureStore keeps it
 * in the iOS Keychain / Android Keystore rather than in plain app storage.
 */

import * as SecureStore from 'expo-secure-store';

import type { Connection } from './types';

const KEY_URL = 'tgtg_alert_url';
const KEY_TOKEN = 'tgtg_alert_token';

export async function saveConnection(connection: Connection): Promise<void> {
  await SecureStore.setItemAsync(KEY_URL, connection.url.replace(/\/+$/, ''));
  await SecureStore.setItemAsync(KEY_TOKEN, connection.token);
}

export async function loadConnection(): Promise<Connection | null> {
  try {
    const [url, token] = await Promise.all([
      SecureStore.getItemAsync(KEY_URL),
      SecureStore.getItemAsync(KEY_TOKEN),
    ]);
    if (!url || !token) return null;
    return { url, token };
  } catch {
    // A corrupted or inaccessible keychain entry should drop the user back to
    // setup rather than crash on launch.
    return null;
  }
}

export async function clearConnection(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(KEY_URL),
    SecureStore.deleteItemAsync(KEY_TOKEN),
  ]);
}
