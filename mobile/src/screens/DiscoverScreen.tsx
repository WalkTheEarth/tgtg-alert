/**
 * A live look at what is near you right now.
 *
 * Doubles as the easiest way to create a watch: tap a result and the store name
 * is prefilled, which beats guessing at the exact spelling TGTG uses.
 *
 * This is an explicit, user-initiated search rather than something that runs on
 * a timer -- every search spends a real API call against an account that gets
 * blocked for being greedy.
 */

import * as Location from 'expo-location';
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Badge, Banner, Button, Card, EmptyState } from '../components';
import { useConnection } from '../ConnectionContext';
import type { TabScreenProps } from '../navigation';
import { colors, radius, spacing, type } from '../theme';
import type { PreviewItem } from '../types';

type Props = TabScreenProps<'Discover'>;

function formatDistance(metres: number | null): string | null {
  if (metres == null) return null;
  return metres < 1000 ? `${Math.round(metres)} m` : `${(metres / 1000).toFixed(1)} km`;
}

export default function DiscoverScreen({ navigation }: Props) {
  const { client } = useConnection();
  const [items, setItems] = useState<PreviewItem[]>([]);
  const [query, setQuery] = useState('');
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const search = useCallback(
    async (position: { latitude: number; longitude: number }, text: string, mode: 'initial' | 'refresh') => {
      if (mode === 'refresh') setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const result = await client.preview({
          latitude: position.latitude,
          longitude: position.longitude,
          radius_km: 10,
          query: text.trim() || undefined,
          limit: 60,
        });
        setItems(result.items);
        setSearched(true);
      } catch (e) {
        setError((e as Error).message);
        setItems([]);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [client],
  );

  useEffect(() => {
    (async () => {
      try {
        const permission = await Location.requestForegroundPermissionsAsync();
        if (!permission.granted) {
          setError('Location permission is needed to search nearby.');
          setLoading(false);
          return;
        }
        const position = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        const next = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        setCoords(next);
        await search(next, '', 'initial');
      } catch {
        setError('Could not get your location.');
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <SafeAreaView style={styles.safe} edges={['bottom']}>
      <View style={styles.searchBar}>
        <TextInput
          placeholder="Filter by store or bag…"
          placeholderTextColor={colors.textFaint}
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={() => coords && search(coords, query, 'refresh')}
          returnKeyType="search"
          autoCapitalize="none"
          style={styles.searchInput}
        />
        <Button
          title="Search"
          variant="secondary"
          onPress={() => coords && search(coords, query, 'refresh')}
          disabled={!coords}
          style={{ minHeight: 44 }}
        />
      </View>

      {error ? (
        <View style={{ paddingHorizontal: spacing.lg }}>
          <Banner tone="bad" title="Search failed" body={error} />
        </View>
      ) : null}

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
          <Text style={[type.caption, { marginTop: spacing.md }]}>
            Asking Too Good To Go what is nearby…
          </Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(item) => item.item_id}
          contentContainerStyle={items.length ? styles.list : { flexGrow: 1 }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => coords && search(coords, query, 'refresh')}
              tintColor={colors.accent}
            />
          }
          ListEmptyComponent={
            searched ? (
              <EmptyState
                title="Nothing found"
                body={
                  query
                    ? `No bags matching "${query}" within 10 km.`
                    : 'No bags are listed near you at the moment. This is normal outside meal times.'
                }
              />
            ) : null
          }
          renderItem={({ item }) => (
            <Pressable
              onPress={() =>
                navigation.navigate('WatchForm', {
                  prefill: {
                    storeName: item.store_name,
                    latitude: coords?.latitude,
                    longitude: coords?.longitude,
                  },
                })
              }
              accessibilityRole="button"
              accessibilityLabel={`Watch ${item.display_name} at ${item.store_name}`}
            >
              <Card style={styles.card}>
                <View style={styles.cardRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={type.heading} numberOfLines={1}>
                      {item.store_name || 'Unknown store'}
                    </Text>
                    <Text
                      style={[type.body, { color: colors.textMuted, marginTop: 2 }]}
                      numberOfLines={1}
                    >
                      {item.display_name}
                    </Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={[type.heading, { color: colors.accent }]}>{item.price}</Text>
                    {formatDistance(item.distance_m) ? (
                      <Text style={type.caption}>{formatDistance(item.distance_m)}</Text>
                    ) : null}
                  </View>
                </View>

                <View style={styles.badges}>
                  {item.quantity > 0 ? (
                    <Badge text={`${item.quantity} left`} tone="good" />
                  ) : (
                    <Badge text="sold out" />
                  )}
                  {item.pickup_end ? (
                    <Badge text={`collect by ${item.pickup_end.slice(11, 16)}`} />
                  ) : null}
                </View>
              </Card>
            </Pressable>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  searchBar: {
    flexDirection: 'row',
    gap: spacing.sm,
    padding: spacing.lg,
    paddingBottom: spacing.sm,
  },
  searchInput: {
    flex: 1,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    color: colors.text,
    fontSize: 15,
    borderWidth: 1,
    borderColor: colors.border,
    minHeight: 44,
  },
  list: { padding: spacing.lg, gap: spacing.md },
  card: { marginBottom: spacing.md },
  cardRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
});
