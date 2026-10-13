/**
 * Holds the paired connection and hands out an `ApiClient`.
 *
 * The context always exists -- `client` and `connection` are null until the
 * user pairs. That matters: the setup screen lives *outside* a session and has
 * to be able to call `pair()` to create one. A context that only existed once
 * paired would leave setup with no way to update app state.
 *
 * While the stored connection is loading we render a spinner rather than the
 * setup screen, so a paired user never sees a flash of "scan the QR code".
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';

import { ApiClient } from './api';
import { clearConnection, loadConnection, saveConnection } from './storage';
import { colors } from './theme';
import type { Connection } from './types';

interface ConnectionState {
  client: ApiClient | null;
  connection: Connection | null;
  ready: boolean;
  pair: (connection: Connection) => Promise<void>;
  unpair: () => Promise<void>;
}

const Context = createContext<ConnectionState | null>(null);

export function ConnectionProvider({ children }: { children: React.ReactNode }) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadConnection()
      .then((stored) => {
        if (!cancelled) setConnection(stored);
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const pair = useCallback(async (next: Connection) => {
    await saveConnection(next);
    setConnection(next);
  }, []);

  const unpair = useCallback(async () => {
    await clearConnection();
    setConnection(null);
  }, []);

  const value = useMemo<ConnectionState>(
    () => ({
      client: connection
        ? new ApiClient(connection)
        : null,
      connection,
      ready,
      pair,
      unpair,
    }),
    [connection, ready, pair, unpair],
  );

  if (!ready) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg, justifyContent: 'center' }}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/**
 * Raw state, including the unpaired case. Use this to decide *whether* to show
 * the paired UI -- `useConnection()` would throw before a pairing exists.
 */
export function useConnectionState(): ConnectionState {
  const value = useContext(Context);
  if (!value) throw new Error('useConnectionState() must be used inside ConnectionProvider');
  return value;
}

/** The paired connection. Throws if called before pairing. */
export function useConnection(): ConnectionState & { client: ApiClient; connection: Connection } {
  const value = useConnectionState();
  if (!value.client || !value.connection) {
    throw new Error('useConnection() used outside a paired session');
  }
  return value as ConnectionState & { client: ApiClient; connection: Connection };
}

/** Pairing actions, safe to call whether or not a session exists. */
export function usePairing(): Pick<ConnectionState, 'pair' | 'unpair' | 'connection'> {
  const value = useContext(Context);
  if (!value) throw new Error('usePairing() must be used inside ConnectionProvider');
  return { pair: value.pair, unpair: value.unpair, connection: value.connection };
}
