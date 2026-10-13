/**
 * Pairing.
 *
 * Two paths, because QR scanning is lovely when it works and useless when the
 * server is behind SSH or on a machine you are already holding: scan the code
 * from `tgtg-alert pair`, or type the URL and token by hand.
 */

import { CameraView, useCameraPermissions } from 'expo-camera';
import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Linking,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Field, Banner } from '../components';
import { usePairing } from '../ConnectionContext';
import { colors, radius, spacing, type } from '../theme';
import { ApiClient } from '../api';
import type { PairingPayload } from '../types';

/** Parse `tgtgalert://pair?d={...}` emitted by `tgtg-alert pair`. */
export function parsePairingLink(data: string): PairingPayload | null {
  try {
    const match = data.match(/[?&]d=([^&]+)/);
    if (!match) return null;
    const payload = JSON.parse(decodeURIComponent(match[1]));
    if (!payload?.url || !payload?.token) return null;
    return { url: String(payload.url), token: String(payload.token), v: Number(payload.v ?? 1) };
  } catch {
    return null;
  }
}

export default function SetupScreen() {
  const { pair } = usePairing();
  const [permission, requestPermission] = useCameraPermissions();
  const [scanning, setScanning] = useState(false);
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function connect(nextUrl: string, nextToken: string) {
    setBusy(true);
    setError(null);
    setNotice(null);

    const cleaned = nextUrl.trim().replace(/\/+$/, '');
    if (!/^https?:\/\//i.test(cleaned)) {
      setError('The server URL should start with http:// or https://');
      setBusy(false);
      return;
    }

    // Verify before storing: pairing with an unreachable server produces an app
    // that looks configured and fails on every screen.
    const client = new ApiClient({ url: cleaned, token: nextToken.trim() });
    try {
      const status = await client.status();
      await pair({ url: cleaned, token: nextToken.trim() });
      if (!status.logged_in) {
        setNotice(
          'Connected, but the server is not logged in to Too Good To Go yet. ' +
            'Run `tgtg-alert login` on it.',
        );
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (scanning) {
    return (
      <View style={{ flex: 1, backgroundColor: '#000' }}>
        <CameraView
          style={StyleSheet.absoluteFill}
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
          onBarcodeScanned={({ data }) => {
            const payload = parsePairingLink(data);
            if (payload) {
              setScanning(false);
              void connect(payload.url, payload.token);
            }
          }}
        />
        <SafeAreaView style={styles.scanOverlay} pointerEvents="box-none">
          <View style={styles.scanFrame} />
          <Text style={styles.scanHint}>Point at the QR code from `tgtg-alert pair`</Text>
          <Button title="Cancel" variant="secondary" onPress={() => setScanning(false)} />
        </SafeAreaView>
      </View>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={[type.title, { marginBottom: spacing.sm }]}>Pair your server</Text>
          <Text style={[type.body, { color: colors.textMuted, marginBottom: spacing.xl }]}>
            This app talks to a watcher you run yourself. Pair it once and it will
            receive alerts wherever you are.
          </Text>

          {error ? <Banner tone="bad" title="Could not connect" body={error} /> : null}
          {notice ? <Banner tone="warn" title="Heads up" body={notice} /> : null}

          <Button
            title="Scan QR code"
            onPress={async () => {
              setError(null);
              if (!permission?.granted) {
                const result = await requestPermission();
                if (!result.granted) {
                  setError(
                    'Camera access is needed to scan the code. You can type the details instead.',
                  );
                  return;
                }
              }
              setScanning(true);
            }}
          />

          <View style={styles.divider}>
            <View style={styles.rule} />
            <Text style={[type.caption, { marginHorizontal: spacing.md }]}>or enter manually</Text>
            <View style={styles.rule} />
          </View>

          <Field
            label="Server URL"
            placeholder="http://192.168.1.42:8787"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            value={url}
            onChangeText={setUrl}
            hint="Run `tgtg-alert pair` on the server to see this."
          />
          <Field
            label="API token"
            placeholder="the token printed by tgtg-alert pair"
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
            value={token}
            onChangeText={setToken}
          />

          <Button
            title="Connect"
            onPress={() => connect(url, token)}
            loading={busy}
            disabled={!url.trim() || !token.trim()}
          />

          <Text style={[type.caption, { marginTop: spacing.xl, textAlign: 'center' }]}>
            Don't have a server yet? See the setup guide.
          </Text>
          <Button
            title="Open the setup guide"
            variant="ghost"
            onPress={() =>
              Linking.openURL('https://github.com/WalkTheEarth/tgtg-alert#quick-start')
            }
            style={{ marginTop: spacing.sm }}
          />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.xl, paddingBottom: spacing.xxl * 2 },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: spacing.xl,
  },
  rule: { flex: 1, height: 1, backgroundColor: colors.border },
  scanOverlay: {
    flex: 1,
    justifyContent: 'space-between',
    padding: spacing.xl,
    alignItems: 'center',
  },
  scanFrame: {
    width: 240,
    height: 240,
    borderWidth: 2,
    borderColor: colors.accent,
    borderRadius: radius.lg,
    marginTop: spacing.xxl * 2,
  },
  scanHint: { color: '#fff', fontSize: 14, textAlign: 'center' },
});
