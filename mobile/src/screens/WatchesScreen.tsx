/** The list of watches the server is enforcing. */

import { useFocusEffect } from '@react-navigation/native';
import React, { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Badge, Banner, Button, Card, EmptyState } from '../components';
import { useConnection } from '../ConnectionContext';
import { colors, spacing, type } from '../theme';
import type { Watch } from '../types';
import type { TabScreenProps } from '../navigation';

type Props = TabScreenProps<'Watches'>;

export function describeWatch(watch: Watch): string {
  const parts: string[] = [];
  if (watch.store_pattern) parts.push(`store contains "${watch.store_pattern}"`);
  if (watch.bag_pattern) parts.push(`bag contains "${watch.bag_pattern}"`);
  if (watch.max_price != null) parts.push(`under ${watch.max_price.toFixed(2)}`);
  return parts.length ? parts.join(' · ') : 'any bag nearby';
}

export default function WatchesScreen({ navigation }: Props) {
  const { client } = useConnection();
  const [watches, setWatches] = useState<Watch[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (mode: 'initial' | 'refresh' = 'initial') => {
      if (mode === 'refresh') setRefreshing(true);
      try {
        setWatches(await client.listWatches());
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

  // Reload on focus so a watch added on another screen appears immediately.
  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  async function toggle(watch: Watch, enabled: boolean) {
    // Optimistic: the switch should respond instantly, and revert on failure.
    setWatches((current) =>
      current.map((w) => (w.id === watch.id ? { ...w, enabled } : w)),
    );
    try {
      await client.updateWatch(watch.id, { enabled });
    } catch (e) {
      setWatches((current) =>
        current.map((w) => (w.id === watch.id ? { ...w, enabled: !enabled } : w)),
      );
      setError((e as Error).message);
    }
  }

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
        data={watches}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={
          watches.length ? styles.list : { flexGrow: 1 }
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => load('refresh')}
            tintColor={colors.accent}
          />
        }
        ListHeaderComponent={
          error ? <Banner tone="bad" title="Could not load watches" body={error} /> : null
        }
        ListEmptyComponent={
          <EmptyState
            title="No watches yet"
            body="A watch tells the server which bags to look out for. Add one, or search what is near you right now."
            action={
              <View style={{ gap: spacing.md, width: '100%' }}>
                <Button
                  title="Add a watch"
                  onPress={() => navigation.navigate('WatchForm', {})}
                />
                <Button
                  title="Search nearby"
                  variant="secondary"
                  onPress={() => navigation.navigate('Discover')}
                />
              </View>
            }
          />
        }
        renderItem={({ item }) => (
          <Card style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={{ flex: 1 }}>
                <Text style={type.heading}>
                  {item.label || item.store_pattern || 'Any bag nearby'}
                </Text>
                <Text style={[type.body, { color: colors.textMuted, marginTop: 2 }]}>
                  {describeWatch(item)}
                </Text>
              </View>
              <Switch
                value={item.enabled}
                onValueChange={(next) => toggle(item, next)}
                trackColor={{ true: colors.accentDim, false: colors.surfaceAlt }}
                thumbColor={item.enabled ? colors.accent : colors.textFaint}
              />
            </View>

            <View style={styles.badges}>
              <Badge text={`${item.radius_km} km`} />
              {item.items_in_stock > 0 ? (
                <Badge text={`${item.items_in_stock} in stock`} tone="good" />
              ) : null}
              <Badge text={`${item.tracked_items} tracked`} />
              {!item.baselined ? <Badge text="awaiting first poll" tone="warn" /> : null}
            </View>

            <View style={styles.actions}>
              <Button
                title="Edit"
                variant="secondary"
                onPress={() => navigation.navigate('WatchForm', { watchId: item.id })}
                style={{ flex: 1 }}
              />
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
  cardHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
});
