# The Too Good To Go problem

Read this before you invest time in setting anything up. It is short, it is
factual, and it is the part most projects bury.

## There is no official API

Too Good To Go does not offer a public API. There is no developer portal you can
sign up for, no API keys, no documentation, and no partner programme an
individual can join. `developers.toogoodtogo.com` exists but sits behind a
corporate SSO — it is a business-to-business surface, not a public one.

Everything this project does relies on the **private API that the official
mobile app talks to**, reverse-engineered by the community. That means:

- Endpoints change without notice. The item endpoint has moved
  `v7 → v8 → v9` over the years, and each move breaks every client until it
  catches up.
- There is no compatibility promise, no deprecation period, and nobody to ask.
- The client library this project uses
  ([`tgtg-python`](https://github.com/ahivert/tgtg-python)) is community-
  maintained. It is in good health — actively developed, ~480 stars — but it is
  one person's spare-time project standing between you and a moving target.

**Expect breakage occasionally.** It is not a sign you configured something
wrong.

## What the Terms of Service say

§7.5 of Too Good To Go's general terms, "TGTG Rules of Conduct", states:

> "You will not use any automated systems, robots or software to extract data
> from the Too Good To Go Marketplace."

And, in the same section:

> "You will not (directly or indirectly): ... (iii) bypass, circumvent or
> attempt to bypass or circumvent any measures we may use to prevent or restrict
> access to the Too Good To Go Marketplace ... (v) use manual or automated
> software, devices, or other processes to 'crawl' or 'spider' any page of the
> Too Good To Go Marketplace; or (vi) harvest or scrape any content from the Too
> Good To Go Marketplace."

Note what is **absent**: there is no personal-use exception, no hobby-project
carve-out, and no threshold below which automation becomes acceptable. One
automated request is, by the letter of the text, a breach.

This is not legal advice, and I am not a lawyer. But the clause is unusually
clear, and it is worth reading it yourself rather than taking my summary:
<https://static.apptoogoodtogo.com/general-terms-conditions/en-us/index.html>

## What that means in practice

The risk is **not** legal action. Nobody is going to sue you over a lunch bag.

The realistic risk is that Too Good To Go blocks you or closes your account.
§11.1 reserves the right to "suspend or terminate your access to the App
including the deletion of your Account at any time with or without notice."

What's actually been observed in the wild:

| Risk | How real |
|---|---|
| **IP-level blocking** | Very real, and the dominant effect. Too Good To Go uses [DataDome](https://datadome.co/) bot protection, which blocks datacenter and VPN ranges as a matter of course. |
| **Rate-limit challenges (CAPTCHA)** | Common. Usually triggered by frequency, a stale client fingerprint, or a flagged IP. |
| **Account suspension** | The terms permit it. The author found no confirmed public report of an account actually being terminated for polling — but a fresh account still gets blocked, which suggests enforcement is at the IP and fingerprint layer rather than the account layer. |
| **Losing order history and credit** | The real practical cost if an account is closed. |

Being polite — polling slowly, backing off when asked — reduces the chance of
running into this. It does not eliminate it.

## If DataDome challenges you

This project will **not** help you defeat bot protection. Specifically, it does
not and will not:

- solve CAPTCHAs automatically,
- forge browser fingerprints to look like a human solved a challenge,
- rotate proxies to evade an IP block.

Those are the parts of §7.5(iii) that are about *circumventing* protections
rather than merely automating access, and they are where a line gets crossed
that this project stays behind.

What it does instead: presents the same client fingerprint the real app would,
paces itself conservatively, and **backs off for hours** when refused rather
than hammering.

If Too Good To Go serves you a challenge anyway, that may simply be the
protection working correctly. There is no clever configuration that
legitimately gets around it, and any guide claiming otherwise is describing
evasion.

## The honest summary

- **This breaks the Terms of Service.** Clearly and unambiguously.
- **The realistic consequence is a blocked IP or a closed account**, not legal
  trouble.
- **Use an account you can afford to lose.** Not one with unspent credit, not
  one with orders you care about.
- **Expect it to break occasionally** when Too Good To Go changes something.
- **There is no compliant way to build this today.** If a tool tells you
  otherwise, it is either wrong or it is the official app.

If any of that is a dealbreaker, the right answer is to stop here. That is a
perfectly reasonable conclusion, and it is why this page is the first thing in
the documentation rather than a footnote.

## Why publish it, then

Because the alternative to a documented, polite, self-hosted tool is not
compliance — it is a scattering of undocumented scripts, each polling as hard as
it likes, with no shared understanding of what breaks and why. A tool that
states the risk plainly, polls conservatively, and backs off properly is a
better neighbour than the status quo, even though it is not a compliant one.

The decision to run it is yours, and it is a decision you are now equipped to
make.
