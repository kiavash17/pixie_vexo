# Pixie: feature list and demo plan

## Everything Pixie does today

**Asking for help (the core loop)**
1. **Help gesture:** double-tap twice → Mom's phone alerts at once; an 8 s voice note and transcript follow.
2. **Help by voice:** Maya calls out "Mommy!", "Dad, where are you?", "Help!" → same alert (live transcript + Gemini).
3. **"Help is coming" on the wrist:** Mom taps *I'm coming* → the band glows green.
4. **Escalation ladder:** no answer → Dad is alerted → a call is simulated; dead ends offer *Call Dad / Mark as handled*.
5. **Fall check:** a fall → the band asks "are you OK?" (purple); a double-tap = OK, silence → urgent alert.

**AI listening (Gemini, on by default)**
6. **Distress detection:** crying, screaming, angry adult voice, each persisting before it alerts, with a clip.
7. **Worrying adult detection:** luring/grooming patterns judged over 2 min of conversation; shows the behaviour and the adult's exact words, keeps 60 s of audio.
8. **AI assessment of every alert:** summary, tone, children/adults nearby, suggested action; it can raise urgency, never lower it.

**Mom's app**
9. **Visual status:** avatar ring, battery, distance, activity and steps, listening, money left.
10. **One colour per event:** help amber, calling teal, crying indigo, angry voice orange, fall purple, worrying adult black and red; urgent adds a red ring.
11. **Listen in** (live sound, 2 min) and **Live captions**; **Send a hug**; **Find band**.
12. **Quiet-time check:** a gentle nudge when Maya hasn't talked with anyone for 1 h (e.g. for autistic children).
13. **For Mom & Dad:** teacher/coach messages for the parent ("pack a lunch tomorrow") become a to-do list.
14. **Full-day transcript:** saved per day, searchable.
15. **Maya's day:** a picture of the day (activity, talking vs. alone, events), stats, an honest AI note and Otter-style *Next steps*.
16. **Patterns & baseline:** weeks and months against Maya's own baseline ("my tummy hurts" 12× vs ~2), non-diagnostic AI patterns with gentle next steps.
17. **Pixie Card:** tap-to-pay pocket money with a daily budget, per-purchase limit, categories, and parent approval when over the limit (`/shop`).
18. **History** with outcome labels (accidental / wanted me / urgent), clear history, offline and low-battery banners, settings.

**Behind the scenes**
19. **Control room** (`/`): live sensor charts, transcript, audio and a terminal monitor.
20. **Testing without a band:** pretend band, Gemini-TTS scene generator, end-to-end scene test.

## Top 10 to demo (in show order, about 4 minutes)

| # | Moment | How to show it | Why it scores |
|---|---|---|---|
| 1 | **Double-tap twice → Mom's phone lights up → *I'm coming* → band glows green** | Real band + phone | The core promise on real hardware |
| 2 | **Maya calls "Mommy!" → alert** | Say it near the band | Voice + AI, no button needed |
| 3 | **Worrying adult**: luring talk → black/red card with behaviour + exact quote | Play `luring.wav` from a laptop speaker next to the band | Most dramatic AI moment; real audio through the band's mic |
| 4 | **Crying / angry adult** → indigo / orange card with the AI summary and voices nearby | Play `scared_child.wav` / `angry_adult.wav` | Shows it understands tone, not just words |
| 5 | **Fall check** → purple "are you OK?"; double-tap answers | Drop the band onto a cushion | Physical, instant, easy to understand |
| 6 | **Escalation ladder** (Mom → Dad → Call, countdown ring) | Leave alert #4 unanswered for a moment | Graded help, not a 911 button |
| 7 | **Maya's day**: rough day picture + Next steps | `/mom?day=rough` | Turns a day of data into one picture |
| 8 | **Patterns & baseline**: tummy aches 12× vs ~2, more time alone | `/mom?patterns=weeks` | Long-term value; the business story |
| 9 | **For Mom & Dad**: a teacher line becomes a to-do | Play a teacher line, or Demo → *Teacher message* | Useful every single day |
| 10 | **Pixie Card**: candy paid; game card → Mom approves on her phone | `/shop` on the laptop, tap the band | Fun, broad appeal, parent stays in control |

Mention in one line each if time allows: Listen in / Live captions, quiet-time check, the control room.

## Before going on stage

- **Band:** charge it (it was at 4 % earlier). Close the dashboard and any other program connected to it. Double-tap → *Connect*.
- **Server:** restart it on the latest code. Open `/mom` on the phone through the tunnel and tap *Turn on alerts*.
- **Warm up the AI notes** so they appear instantly: open *Rough day* and *Patterns* once beforehand.
- **Test clips:** regenerate them if needed with `python tests/make_test_audio.py testaudio` (Gemini TTS). Practise playing them at a volume the band hears.
- **Backup:** if the band or Wi-Fi fails, `/mom?demo=1` has buttons that simulate every event.
- **Privacy line for judges:** the blue light always shows when the mic is on. Audio is kept only as short clips around alerts; the words heard are saved as a transcript while Listening mode is on (the default), and a parent can turn it off or clear history at any time. A real product needs consent from the people nearby.
