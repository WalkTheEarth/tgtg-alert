/**
 * Create or edit a watch.
 *
 * Location is the one field that cannot be left blank -- the server searches
 * outward from a point -- so it is resolved from the device by default and can
 * be overridden by hand for a place you are not standing in.
 */

import * as Location from 'expo-location';
import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Banner, Button, Card, Field } from '../components';
import { useConnection } from '../ConnectionContext';
import type { WatchFormProps } from '../navigation';
import { colors, spacing, type } from '../theme';

type Props = WatchFormProps;

const RADIUS_CHOICES = [1, 2, 5, 10, 20];

export default function WatchFormScreen({ navigation, route }: Props) {
  const { client } = useConnection();
  const watchId = route.params?.watchId;
  const prefill = route.params?.prefill;
  const editing = watchId != null;

  const [label, setLabel] = useState('');
  const [store, setStore] = useState(prefill?.storeName ?? '');
  const [bag, setBag] = useState(prefill?.bagName ?? '');
  const [maxPrice, setMaxPrice] = useState('');
  const [radius, setRadius] = useState(5);
  const [notifyOnIncrease, setNotifyOnIncrease] = useState(false);
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(
    prefill?.latitude != null && prefill?.longitude != null
      ? { latitude: prefill.latitude, longitude: prefill.longitude }
      : null,
  );
  const [locating, setLocating] = useState(false);
  const [loading, setLoading] = useState(editing);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Resolve a location up front for new watches: without one the form cannot
  // be submitted, and asking for it at save time is a worse moment to fail.
  useEffect(() => {
    if (coords || editing) return;
    void useCurrentLocation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!editing) return;
    let cancelled = false;
    (async () => {
      try {
        const watches = await client.listWatches();
        const watch = watches.find((w) => w.id === watchId);
        if (cancelled || !watch) return;
        setLabel(watch.label);
        setStore(watch.store_pattern ?? '');
        setBag(watch.bag_pattern ?? '');
        setMaxPrice(watch.max_price != null ? String(watch.max_price) : '');
        setRadius(watch.radius_km);
        setNotifyOnIncrease(watch.notify_on_increase);
        setCoords({ latitude: watch.latitude, longitude: watch.longitude });
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, editing, watchId]);

  async function useCurrentLocation() {
    setLocating(true);
    setError(null);
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted) {
        setError(
          'Location permission is needed to know where to search. You can also enter coordinates by hand.',
        );
        return;
      }
      const position = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      setCoords({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
      });
    } catch {
      setError('Could not get your location. You can enter coordinates by hand.');
    } finally {
      setLocating(false);
    }
  }

  async function save() {
    if (!coords) {
      setError('A location is required — tap "Use my location" or enter coordinates.');
      return;
    }

    setSaving(true);
    setError(null);

    const trimmedPrice = maxPrice.trim();
    let parsedPrice: number | null = null;
    if (trimmedPrice) {
      parsedPrice = Number(trimmedPrice.replace(',', '.'));
      if (Number.isNaN(parsedPrice) || parsedPrice < 0) {
        setError('The price limit should be a number, like 5 or 4.50');
        setSaving(false);
        return;
      }
    }

    // Empty strings must become null, not "", or the server would store a
    // pattern that matches nothing.
    const payload = {
      label: label.trim(),
      store_pattern: store.trim() || null,
      bag_pattern: bag.trim() || null,
      max_price: parsedPrice,
      latitude: coords.latitude,
      longitude: coords.longitude,
      radius_km: radius,
      notify_on_increase: notifyOnIncrease,
    };

    try {
      if (editing) {
        await client.updateWatch(watchId, payload);
      } else {
        await client.createWatch(payload);
      }
      navigation.goBack();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function confirmDelete() {
    Alert.alert('Delete this watch?', 'The server will stop looking for these bags.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await client.deleteWatch(watchId!);
            navigation.goBack();
          } catch (e) {
            setError((e as Error).message);
          }
        },
      },
    ]);
  }

  function confirmRebaseline() {
    Alert.alert(
      'Re-baseline this watch?',
      'It forgets what is currently available and starts fresh, so you will not be ' +
        'alerted about bags that were already there. Useful after the server has been off for a while.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Re-baseline',
          onPress: async () => {
            try {
              await client.rebaselineWatch(watchId!);
              navigation.goBack();
            } catch (e) {
              setError((e as Error).message);
            }
          },
        },
      ],
    );
  }

  if (loading) {
    return (
      <View style={[styles.safe, { justifyContent: 'center' }]}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['bottom']}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {error ? <Banner tone="bad" title="Problem" body={error} /> : null}

          <Field
            label="Name (optional)"
            placeholder="Coffee near work"
            value={label}
            onChangeText={setLabel}
          />

          <Field
            label="Store name contains"
            placeholder="Blank Street"
            autoCapitalize="none"
            value={store}
            onChangeText={setStore}
            hint="Leave blank to watch every store in range. Not case sensitive."
          />

          <Field
            label="Bag name contains (optional)"
            placeholder="Magic Bag"
            autoCapitalize="none"
            value={bag}
            onChangeText={setBag}
            hint="Narrow to one bag type at those stores."
          />

          <Field
            label="Maximum price (optional)"
            placeholder="5.00"
            keyboardType="decimal-pad"
            value={maxPrice}
            onChangeText={setMaxPrice}
          />

          <Text style={[type.label, { marginBottom: spacing.sm }]}>Search radius</Text>
          <View style={styles.chips}>
            {RADIUS_CHOICES.map((choice) => (
              <Button
                key={choice}
                title={`${choice} km`}
                variant={radius === choice ? 'primary' : 'secondary'}
                onPress={() => setRadius(choice)}
                style={{ flexGrow: 1, minWidth: 72, minHeight: 40 }}
              />
            ))}
          </View>

          <Card style={{ marginTop: spacing.xl }}>
            <Text style={type.label}>Location</Text>
            <Text style={[type.body, { color: colors.textMuted, marginTop: spacing.xs }]}>
              {coords
                ? `${coords.latitude.toFixed(4)}, ${coords.longitude.toFixed(4)}`
                : 'Not set — required'}
            </Text>
            <Button
              title={locating ? 'Locating…' : 'Use my location'}
              variant="secondary"
              onPress={useCurrentLocation}
              loading={locating}
              style={{ marginTop: spacing.md }}
            />
          </Card>

          <Card style={{ marginTop: spacing.md }}>
            <Text style={type.heading}>Alert me when the count goes up too</Text>
            <Text style={[type.body, { color: colors.textMuted, marginTop: spacing.xs }]}>
              By default you are told when a bag appears or returns after selling out.
              Enabling this also pings you when an available bag's count rises — it can
              get noisy.
            </Text>
            <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md }}>
              <Button
                title="Off"
                variant={!notifyOnIncrease ? 'primary' : 'secondary'}
                onPress={() => setNotifyOnIncrease(false)}
                style={{ flex: 1 }}
              />
              <Button
                title="On"
                variant={notifyOnIncrease ? 'primary' : 'secondary'}
                onPress={() => setNotifyOnIncrease(true)}
                style={{ flex: 1 }}
              />
            </View>
          </Card>

          <Button
            title={editing ? 'Save changes' : 'Create watch'}
            onPress={save}
            loading={saving}
            disabled={!coords}
            style={{ marginTop: spacing.xl }}
          />

          {editing ? (
            <View style={{ gap: spacing.md, marginTop: spacing.lg }}>
              <Button title="Re-baseline" variant="secondary" onPress={confirmRebaseline} />
              <Button title="Delete watch" variant="danger" onPress={confirmDelete} />
            </View>
          ) : null}

          <Text style={[type.caption, { marginTop: spacing.xl, textAlign: 'center' }]}>
            The first poll records what is already available without alerting, so
            you will not get a burst of notifications when you add a watch.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, paddingBottom: spacing.xxl * 2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
});
