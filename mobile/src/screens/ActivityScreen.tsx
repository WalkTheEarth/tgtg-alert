/** What has actually been alerted, and whether it got delivered. */

import { useFocusEffect } from '@react-navigation/native';
import React, { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Badge, Banner, Card, EmptyState } from '../components';
import { useConnection } from '../ConnectionContext';
import { colors, spacing, type } from '../theme';
import type { AlertRecord } from '../types';

/**
 * TGTG timestamps are naive UTC from SQLite (`datetime('now')`), so they need
 * an explicit Z before parsing or every alert looks hours old.
 */
function relativeTime(value: string): string {
  const parsed = new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}Z`);
  if (Number.isNaN(parsed.getTime())) return value;

  const seconds = Math.round((Date.now() - parsed.getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)} d ago`;
  return parsed.toLocaleDateString();
}

export default function ActivityScreen() {
  const { client } = useConnection();
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (mode: 'initial' | 'refresh' = 'initial') => {
      if (mode === 'refresh') setRefreshing(true);
      try {
        setAlerts(await client.listAlerts(100));
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [client],
  );

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['bottom']}>
      <FlatList
        data={alerts}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={alerts.length ? styles.list : { flexGrow: 1 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => load('refresh')}
            tintColor={colors.accent}
          />
        }
        ListHeaderComponent={
          error ? <Banner tone="bad" title="Could not load activity" body={error} /> : null
        }
        ListEmptyComponent={
          <EmptyState
            title="Nothing yet"
            body="Once a watched bag becomes available it will show up here, whether or not the notification reached your phone."
          />
        }
        renderItem={({ item }) => (
          <Card style={styles.card}>
            <View style={styles.row}>
              <Text style={[type.heading, { flex: 1 }]} numberOfLines={2}>
                {item.title}
              </Text>
              <Text style={type.caption}>{relativeTime(item.created_at)}</Text>
            </View>
            <Text style={[type.body, { color: colors.textMuted, marginTop: spacing.xs }]}>
              {item.body}
            </Text>
            <View style={styles.badges}>
              {item.devices_err > 0 ? (
                <Badge text="delivery failed" tone="bad" />
              ) : item.devices_ok > 0 ? (
                <Badge text={`sent to ${item.devices_ok}`} tone="good" />
              ) : (
                <Badge text="no device" tone="warn" />
              )}
              {item.watch_label ? <Badge text={item.watch_label} /> : null}
            </View>
          </Card>
        )}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, backgroundColor: colors.bg, justifyContent: 'center' },
  list: { padding: spacing.lg, gap: spacing.md },
  card: { marginBottom: spacing.md },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
});
