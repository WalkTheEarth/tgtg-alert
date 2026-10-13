/**
 * Push registration and notification presentation.
 *
 * The details here are load-bearing, not boilerplate:
 *
 * - **The Android channel is created before the token is requested.** Its
 *   importance is fixed at creation and can never be raised afterwards -- only
 *   a *new* channel id can do that -- so `CHANNEL_ID` is versioned. Shipping a
 *   low-importance channel and "fixing" it later would mean every existing
 *   install silently never shows a heads-up alert.
 *
 * - **Importance is MAX.** A stock alert that arrives silently in the tray is
 *   indistinguishable from no alert at all, which is the entire product.
 *
 * - **iOS uses the `time-sensitive` interruption level**, which breaks through
 *   Focus modes without needing Apple's separate critical-alert entitlement.
 */

import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

/** Bump the suffix if the importance ever needs to change; never reuse an id. */
export const CHANNEL_ID = 'tgtg-alerts-v1';

let handlerInstalled = false;

export function installNotificationHandler(): void {
  if (handlerInstalled) return;
  handlerInstalled = true;

  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      // Show it even with the app open: the user asked to be interrupted.
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

export async function ensureAndroidChannel(): Promise<void> {
  if (Platform.OS !== 'android') return;
  await Notifications.setNotificationChannelAsync(CHANNEL_ID, {
    name: 'Bag alerts',
    description: 'Tells you when a watched bag becomes available.',
    importance: Notifications.AndroidImportance.MAX,
    sound: 'default',
    // The server sends time-sensitive alerts; let them light the screen and
    // bypass Do Not Disturb the way the user configured.
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
    bypassDnd: false,
    enableVibrate: true,
    vibrationPattern: [0, 250, 250, 250],
  });
}

export interface RegistrationResult {
  token: string | null;
  /** Set when registration could not complete, phrased for display. */
  problem: string | null;
}

export async function registerForPush(): Promise<RegistrationResult> {
  // The channel must exist before the first notification arrives.
  await ensureAndroidChannel();

  if (!Device.isDevice) {
    // Simulators cannot receive push at all -- and on iOS the token request
    // simply fails. Say so plainly instead of showing a confusing error.
    return {
      token: null,
      problem:
        'Push notifications need a real device. Emulators and simulators cannot receive them.',
    };
  }

  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;

  if (status !== 'granted') {
    const requested = await Notifications.requestPermissionsAsync();
    status = requested.status;
  }

  if (status !== 'granted') {
    return {
      token: null,
      problem:
        'Notification permission was declined. Enable it in your device settings to receive alerts.',
    };
  }

  try {
    const token = (await Notifications.getExpoPushTokenAsync()).data;
    return { token, problem: null };
  } catch (error) {
    return {
      token: null,
      problem:
        'Could not obtain a push token. This usually means the app is running in Expo Go ' +
        'rather than a development or production build.',
    };
  }
}

/**
 * The most recent token, or null.
 *
 * Tokens rotate -- on reinstall, on restore, and occasionally on their own --
 * so the app re-registers on every launch rather than trusting what it stored.
 * The server upserts on the token, so this is cheap and idempotent.
 */
export async function currentPushToken(): Promise<string | null> {
  try {
    const permission = await Notifications.getPermissionsAsync();
    if (permission.status !== 'granted') return null;
    if (!Device.isDevice) return null;
    return (await Notifications.getExpoPushTokenAsync()).data;
  } catch {
    return null;
  }
}
