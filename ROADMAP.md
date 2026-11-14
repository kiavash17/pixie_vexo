# Pixie — Product Roadmap

*Pixie (formerly HelpBand): a screenless wearable that lets a child — later an elder — summon
their guardian, and know help is coming.* "Need me? Tap twice."

Not a phone, not a tracker, not a 911 button. Pixie is the communication layer between
independence and emergency: graded guardian attention, with an acknowledgement back to the wrist.

## What changed since the HelpBand briefs

| HelpBand assumption | Pixie today | Why |
|---|---|---|
| Feasycom BP107D / ESP32 prototype | **Vexo Open band** (accel + gyro, gestures, mic, RGB LED, BLE) | We have it in hand and it streams everything we need |
| Physical button press | **Double-tap** gesture (tap alone fires on bumps) | No button on the band; double-tap is deliberate |
| Haptic "COMING" buzz-back | **LED acknowledgement pattern** | Band has no vibration motor. Mic must be off for the LED to change |
| No AI until V3 | **AI guardian assistant from day one, bounded by rules** | Rules decide the floor; AI adds context, a summary and can only *raise* urgency |
| No microphone | **Mic only after a trigger** (short voice note), never continuous | Gives the guardian context; keeps the privacy promise |
| Phone app gateway | Laptop server now → guardian phone web app over HTTPS | Fastest path to a working loop |

## Principles (unchanged)

1. Do the most useful thing before the most dramatic thing. 911 is never the default.
2. The wearer must know the request was received. A silent failure is the worst failure.
3. Rules are transparent and always win; AI explains and may escalate, never suppresses.
4. Privacy is a feature: no continuous listening, no location-first tracking.
5. Measure independence granted, not button presses.

## Horizons

### H0 — VexoHacks demo (today, by 6:00 pm)
Prove the full loop live on stage: **double-tap → guardian alert with voice + AI summary →
guardian taps COMING → band glows "help is coming"**, plus escalation when nobody answers.
Builds on the existing control room (`server.py`).

### H1 — Pilot-ready prototype (weeks 1–6)
Reliable enough for 10–20 families to use at a playground. Guardian phone as the gateway
(no laptop), real push notifications, offline/low-battery alerts, event + outcome logging,
second guardian. Measure accidental-trigger rate and acknowledgement latency.

### H2 — V1 product (months 2–8)
Custom, cute band with a real button, haptic motor and LED; guardian app (iOS/Android);
multi-guardian routing, on-duty handoff (babysitter/playdate modes); ~$29–49 hardware +
~$3–5/mo. Pilot of 50–100 families measuring independence minutes, retention, willingness to pay.

### H3 — V2 range + elder variant (months 9–15)
LTE-M / Cat-1 bis so it works beyond phone range; location only on alert. Elder variant with
fall/impact check-ins and inactivity rules ("family first, escalate only when needed").

### H4 — V3 intelligence + platform (15+ months)
Personalized anomaly detection from labeled history (habitual tapper vs. rare sudden alert,
distress cues on-device); escalation engine accepts other devices (watches, phones).

## Prioritized feature backlog

| # | Feature | Horizon | Notes |
|---|---|---|---|
| 1 | Help trigger: double-tap → help event | H0 | Debounce; ignore during high motion; repeat double-tap = urgent |
| 2 | COMING acknowledgement on the band | H0 | Mic off → LED pattern (e.g. green pulse = coming, amber = waiting) |
| 3 | Guardian web app (phone) | H0 | Alert card, sound, COMING button, live band status; works over the tunnel |
| 4 | Escalation ladder (rules) | H0 | Normal → urgent on repeat; no ack in 30 s → louder + second guardian |
| 5 | Voice note on trigger | H0 | Mic on for ~8 s after a trigger only; transcript + audio attached to the alert |
| 6 | AI guardian assistant | H0 | Fuses transcript + motion context + history → urgency, one-line summary, "why" |
| 7 | Trust layer: band health | H0/H1 | Connected / battery / signal on guardian screen; alert when band goes offline |
| 8 | Event log + outcome labels | H0/H1 | Guardian tags each alert: accidental / wanted me / urgent → dataset for later AI |
| 9 | Fall / impact check | H0 stretch, H3 | Free-fall + stillness → "are you OK?" LED; double-tap = OK, else escalate |
| 10 | Multi-guardian + on-duty handoff | H1 | Primary → secondary → backup; babysitter/playdate modes |
| 11 | Phone as gateway (no laptop) | H1 | Web Bluetooth on Android Chrome or native app; background reliability tests |
| 12 | Real push / SMS / call escalation | H1 | Notifications that beat silent mode; automated call as a late step |
| 13 | Range awareness ("drifting away") | H1 | Signal-strength trend, opt-in, framed as a nudge not tracking |
| 14 | Pilot metrics dashboard | H1 | Independence minutes, ack latency, false-alert rate, wear time |
| 15 | Custom hardware with haptic + button | H2 | Cute, durable, easy to find by touch, hard to remove accidentally |
| 16 | Subscription + family accounts | H2 | Free basic; premium for multi-guardian, history, automations |
| 17 | Cellular (LTE-M) + location on alert | H3 | Only after range pain is proven in the pilot |
| 18 | Elder variant: check-ins, inactivity | H3 | Same escalation engine, different ergonomics and risk model |
| 19 | Personalized anomaly detection | H4 | Trained on labeled outcomes; on-device where possible |
| 20 | Platform: third-party devices | H4 | Escalation engine as the moat, the band as the wedge |

## Top 10 priorities (in order)

1. **Help trigger** — double-tap on the band raises a help event; repeat double-tap raises urgency.
2. **"Help is coming" on the wrist** — guardian's COMING turns the band's LED into a distinct acknowledgement pattern.
3. **Guardian app** — phone-friendly page: alert card with sound, COMING button, live band status.
4. **Escalation ladder** — transparent rules: unanswered for 30 s → louder alert → second guardian.
5. **Voice note on trigger** — mic opens for a few seconds only after a help request; transcript and audio go with the alert.
6. **AI guardian assistant** — reads transcript + motion + history, writes a one-line summary and urgency with its reasons; can raise but never lower the rule-based level.
7. **Trust layer** — guardian always sees connected / battery / signal, and gets alerted when the band drops off.
8. **Event log + outcome labels** — every alert is logged and the guardian tags it (accidental / wanted me / urgent).
9. **Fall / impact check** — free-fall then stillness asks "are you OK?" on the LED; no OK → escalate (elder-variant preview).
10. **Multi-guardian routing** — primary → secondary → backup, with on-duty handoff for babysitters and playdates.

## Metrics that decide what comes next

- **Independence minutes** (killer metric): extra time/distance guardians allow vs. baseline.
- Alert delivery + acknowledgement reliability (target: no silent failures).
- Accidental-alert rate (< 1/day per wearer).
- Acknowledgement latency (tap → COMING on the wrist).
- Voluntary wear rate after 2 weeks (~70%+), weekly retention, willingness to pay ($40 + $5/mo).
