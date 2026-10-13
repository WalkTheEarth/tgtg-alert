/**
 * Server health, connection details, and the way out.
 *
 * The status panel exists because the failure that matters most for this app is
 * *silent*: TGTG's bot protection can start refusing the server while it keeps
 * running and logging nothing the user would ever see. Showing "blocked N times
 * in the last day" turns that into something actionable.
 */

import { useFocusEffect } from '@react-navigation/native';
import React, { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Badge, Banner, Button, Card } from '../components';
import { useConnection, usePairing } from '../ConnectionContext';
import { registerForPush } from '../notifications';
import { colors, spacing, type } from '../theme';
import type { ServerStatus } from '../types';

export default function SettingsScreen() {
  const { client, connection } = useConnection();
  const { unpair } = usePairing();
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pushMessage, setPushMessage] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  const load = useCallback(
    async (mode: 'initial' | 'refresh' = 'initial') => {
      if (mode === 'refresh') setRefreshing(true);
      try {
        setStatus(await client.status());
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

  async function reRegisterPush() {
    setPushMessage(null);
    const result = await registerForPush();
    if (result.problem) {
      setPushMessage(result.problem);
      return;
    }
    if (!result.token) {
      setPushMessage('No push token was returned.');
      return;
    }
    try {
      await client.registerDevice(result.token, 'mobile', 'This phone');
      setPushMessage('This device is registered for alerts.');
      await load('refresh');
    } catch (e) {
      setPushMessage((e as Error).message);
    }
  }

  async function sendTest() {
    setTesting(true);
    setPushMessage(null);
    try {
      const result = await client.testNotify();
      setPushMessage(
        result.errors > 0
          ? `Sent to ${result.sent}, but ${result.errors} failed: ${result.messages.join(', ')}`
          : 'Test alert sent — it should arrive in a moment.',
      );
    } catch (e) {
      setPushMessage((e as Error).message);
    } finally {
      setTesting(false);
    }
  }

  function confirmUnpair() {
    Alert.alert(
      'Unpair this device?',
      'The app will forget the server and stop showing your watches. The server keeps running.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Unpair', style: 'destructive', onPress: () => void unpair() },
      ],
    );
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  const lastRun = status?.last_run;
  const intervalMinutes = status ? Math.round(status.poll_interval_seconds / 60) : null;

  return (
    <SafeAreaView style={styles.safe} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => load('refresh')}
            tintColor={colors.accent}
          />
        }
      >
        {error ? <Banner tone="bad" title="Cannot reach the server" body={error} /> : null}

        {status && !status.logged_in ? (
          <Banner
            tone="warn"
            title="Server is not logged in to Too Good To Go"
            body="Run `tgtg-alert login` on the server. Until then it cannot see any bags."
          />
        ) : null}

        {status && status.blocked_in_last_24h > 0 ? (
          <Banner
            tone="warn"
            title={`Blocked by Too Good To Go ${status.blocked_in_last_24h}× in the last day`}
            body="Alerts are paused while this happens. The usual cause is running the server on a datacenter or VPN IP. A home connection is far more reliable."
          />
        ) : null}

        <Card>
          <Text style={[type.heading, { marginBottom: spacing.md }]}>Server</Text>
          <Row label="Address" value={connection.url} />
          <Row label="Account" value={status?.account ?? 'not logged in'} />
          <Row
            label="Checks for bags"
            value={intervalMinutes != null ? `every ${intervalMinutes} min` : '—'}
          />
          <Row label="Watches" value={String(status?.watches ?? '—')} />
          <Row label="Paired devices" value={String(status?.devices ?? '—')} />
          <Row label="Server version" value={status?.version ?? '—'} />
        </Card>

        <Card style={{ marginTop: spacing.md }}>
          <Text style={[type.heading, { marginBottom: spacing.md }]}>Last check</Text>
          {lastRun ? (
            <>
              <Row label="When" value={lastRun.at ?? '—'} />
              <Row label="Bags seen" value={String(lastRun.items_seen)} />
              <Row label="Matched your watches" value={String(lastRun.matched)} />
              <Row label="Alerts sent" value={String(lastRun.alerts)} />
              <View style={styles.badgeRow}>
                {lastRun.blocked ? (
                  <Badge text="blocked on this run" tone="bad" />
                ) : lastRun.errors > 0 ? (
                  <Badge text={`${lastRun.errors} error(s)`} tone="warn" />
                ) : (
                  <Badge text="healthy" tone="good" />
                )}
              </View>
              {lastRun.note ? (
                <Text style={[type.caption, { marginTop: spacing.sm }]}>{lastRun.note}</Text>
              ) : null}
            </>
          ) : (
            <Text style={[type.body, { color: colors.textMuted }]}>
              The server has not completed a check yet. Give it a few minutes.
            </Text>
          )}
        </Card>

        <Card style={{ marginTop: spacing.md }}>
          <Text style={[type.heading, { marginBottom: spacing.sm }]}>Notifications</Text>
          <Text style={[type.body, { color: colors.textMuted, marginBottom: spacing.md }]}>
            Re-register if alerts stop arriving, or after reinstalling the app.
          </Text>
          {pushMessage ? (
            <Banner tone="info" title={pushMessage} />
          ) : null}
          <Button
            title="Register this device"
            variant="secondary"
            onPress={reRegisterPush}
            style={{ marginBottom: spacing.sm }}
          />
          <Button title="Send a test alert" onPress={sendTest} loading={testing} />
        </Card>

        <Card style={{ marginTop: spacing.md }}>
          <Text style={[type.heading, { marginBottom: spacing.sm }]}>Danger zone</Text>
          <Button title="Unpair this device" variant="danger" onPress={confirmUnpair} />
        </Card>

        <Text style={[type.caption, { marginTop: spacing.xl, textAlign: 'center' }]}>
          Uses an unofficial Too Good To Go API, which is against their terms of service.
          Use an account you can afford to lose.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={[type.body, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[type.body, styles.rowValue]} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, backgroundColor: colors.bg, justifyContent: 'center' },
  content: { padding: spacing.lg, paddingBottom: spacing.xxl * 2 },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.xs + 2,
    gap: spacing.lg,
  },
  rowValue: { flexShrink: 1, textAlign: 'right' },
  badgeRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
});
