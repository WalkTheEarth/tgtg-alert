# Mobile app

Using it, and building it for Android and iOS.

The app is a **thin client**. It does no polling, holds no Too Good To Go
credentials, and talks only to your own server. Close it and alerts still
arrive — the server does the work.

---

## Pairing

Your phone needs to reach your server. On the same wifi that is automatic; from
elsewhere you need a reverse proxy or a mesh network — see
[Deployment](deployment.md#reaching-it-from-outside-your-network).

On the server:

```bash
tgtg-alert pair
```

```
Scan this with the Too Good To Go Alert app:

█████▀▀▀▀▀▀▀█████▀▀▀███▀██▀███▀▀█▀█▀███▀█▀▀▀▀▀▀▀████
█ █▀▀▀█ █  ▀█▀▀ ▀▀█ ▄▄█▄█ ▄█▄ █▀▄▄██ ██ █▀▀▀█ █
...

  Server URL : http://192.168.1.42:8787
  API token  : 8Kd2mQ...
```

In the app, tap **Scan QR code** and point it at the terminal. Or type the URL
and token in by hand — useful when the server is on a box you are already SSH'd
into.

**The QR contains your API token.** A screenshot of it is equivalent to a
password: it grants full control of your watches and the ability to push
notifications to your phone.

The app verifies the connection *before* saving, so a typo fails immediately
rather than producing an app that looks configured and errors on every screen.

### Multiple phones

Run `pair` again and scan on the second device. The token is unchanged, so the
first phone keeps working. Every paired phone gets every alert. Manage them with
`tgtg-alert devices`.

---

## The screens

### Watches

The rules the server is enforcing. Each card shows the pattern in plain words,
the radius, how many items the server has seen match, and how many currently
have bags.

- **The switch** pauses a watch without deleting it. It is optimistic — the
  toggle moves immediately and reverts if the server rejects it.
- **Edit** opens the same form used to create a watch.
- **Pull down** to refresh.

A watch shows an **awaiting first poll** badge until the server has completed
one pass. Nothing alerts before then — that is the baseline, and it is
deliberate (see [How it works](how-it-works.md#when-it-alerts-you)).

### Discover

A live look at what is near you, right now. This is pulled fresh from Too Good
To Go on demand, so it spends a real API call — treat it as an explicit action,
not something to leave refreshing.

Its real purpose is **finding out what things are actually called**. Tap any
result and the store name is prefilled into a new watch, which beats guessing at
the spelling TGTG uses.

Requires location permission. Filter by store or bag with the search box.

### Activity

Everything the server has alerted, whether or not the notification reached your
phone. Each entry shows when, what, and delivery status:

| Badge | Meaning |
|---|---|
| `sent to N` | Delivered to N devices. |
| `delivery failed` | Expo or APNs/FCM rejected it. |
| `no device` | No phone was paired at the time. |

This is the place to check when you suspect you missed something. An alert
appearing here but not on your phone is a delivery problem; an alert *not*
appearing here is a matching or polling problem. Very different diagnoses.

### Settings

Server health and connection details — the screen to open when something seems
wrong.

- **Account** — which TGTG account the server is logged in as.
- **Checks for bags** — the configured poll interval.
- **Last check** — what the most recent pass found, with a health badge.
- **Blocked N times in the last day** — banners loudly when Too Good To Go has
  been refusing the server. This is the failure that is otherwise completely
  silent, so it is surfaced prominently.
- **Register this device** — re-registers the push token. Use after
  reinstalling, or if alerts stop.
- **Send a test alert** — same as `tgtg-alert test-notify` from the app.
- **Unpair** — forgets the server. The server keeps running; another phone can
  still be paired.

---

## Notifications

### Android

The app creates a notification channel called **Bag alerts** with **maximum
importance** at startup, before requesting a push token.

That ordering is not incidental. Channel importance is fixed when the channel is
created and **can never be raised afterwards** — only a new channel id can do
that. Shipping a low-importance channel and fixing it later would leave every
existing install silently broken, so the channel id carries a version
(`tgtg-alerts-v1`).

Android 13+ also requires the runtime notification permission, which the app
requests during registration.

### iOS

iOS notifications need the permission prompt accepted, and the app requests
`time-sensitive` interruption level, which breaks through Focus modes without
needing Apple's separate critical-alert entitlement (which they do not grant for
shopping alerts).

Two things that catch people out:

- **The iOS Simulator cannot receive push notifications.** Ever. Use a real
  device.
- **Push does not work in Expo Go** from SDK 53 onward. You need a development
  build or a production build.

### If alerts stop arriving

1. **Settings → Send a test alert.** If this works, delivery is fine and the
   problem is matching or polling.
2. **Settings → Register this device.** Tokens rotate on reinstall and
   occasionally on their own. The app re-registers on every launch, but this
   forces it.
3. **Check the server log** for delivery errors.
4. **On Android**, check the channel importance has not been lowered by the user
   in system settings — the app cannot detect that.

---

## Building

Requires Node 18+ and the Expo tooling. The app lives in `mobile/`.

```bash
cd mobile
npm install
npx expo start          # dev server; scan with Expo Go to poke at the UI
```

> Expo Go is fine for looking at screens, but **push notifications will not
> work in it** from SDK 53. For anything involving alerts you need a development
> build: `npx expo run:android`.

### Android

Builds on any OS, including Linux.

```bash
npx eas build --platform android --profile preview    # APK, for sideloading
npx eas build --platform android --profile production # AAB, for Play Store
```

Or build locally with the Android SDK installed:

```bash
npx expo run:android --variant release
```

### iOS

**This requires macOS or a cloud build.** Apple's toolchain only runs on macOS —
there is no legal or practical way to produce a signed `.ipa` on Linux.

[EAS Build](https://expo.dev/eas) compiles and signs in the cloud from any OS,
and handles certificates and provisioning profiles for you. Free tier is 15
builds/month, which is plenty.

```bash
npx eas build --platform ios --profile preview
```

You need an **Apple Developer Program membership ($99/year)** for a build you
can install on a device or ship to TestFlight. There is no way around this for
iOS — it is Apple's requirement, not Expo's or this project's.

A simulator build is possible without a paid account, but it needs a Mac and
cannot receive push.

### Before you build your own

If you change `app.json`, note these are load-bearing:

- **`scheme`** (`tgtgalert`) — must stay, it is the pairing URL scheme.
- **`bundleIdentifier` / `package`** (`com.tgtgalert.app`) — change these to
  your own before shipping to a store, or you will collide with this project's
  identifiers.
- **Permissions** — camera (QR pairing) and location (Discover, watch centres).
  Removing them breaks those screens.

---

## How the app talks to the server

Plain HTTPS with a bearer token. No accounts, no sessions, no OAuth — the token
*is* the auth.

If you want to build your own client, the whole surface is documented in
[HTTP API](api.md). Everything the app does is a few REST calls.

---

## Security notes

- The server URL and token are stored in the **OS keychain** (iOS Keychain /
  Android Keystore) via `expo-secure-store`, not in plain app storage.
- The app never sees your Too Good To Go credentials. It cannot place orders and
  cannot read your purchase history.
- **Unpair** in Settings wipes the stored token from the device. To revoke it
  server-side as well, rotate `TGTG_API_TOKEN` — see
  [Security](security.md#if-a-secret-leaks).
