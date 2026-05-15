---
title: "Hi-Res Whole House Audio with Lyrion Music Server, PiCorePlayer, and WIIM"
date: 2024-12-10
tags: ["homelab", "audio", "raspberry-pi", "docker", "synology", "lyrion", "self-hosted", "hi-res-audio"]
description: "How I built a whole-house hi-res audio system using Lyrion Music Server on Synology NAS, PiCorePlayer on Raspberry Pi, and WIIM amplifiers — playing 32-bit/384kHz FLAC and DSD from a local library, with Tidal and Spotify built in."
---

The whole reason I built this instead of buying a Sonos or any other off-the-shelf system: **hi-res audio**. Proprietary systems resample or cap your music before it reaches the speakers. I wanted 24-bit/192kHz FLAC files from my local library to play at exactly that quality, end to end, across every room in the house simultaneously.

What I ended up with is a fully self-hosted setup built around open-source software, a few Raspberry Pis, and WIIM players and 12-channel amplifiers. Lyrion Music Server passes hi-res files through unmodified. WIIM Pro decodes them at full quality. Nothing in the chain caps or resamples. And it's perfectly synchronized across every room.

This post walks through the complete architecture, how everything connects, and how I play my local hi-res library alongside Tidal and Spotify streaming.

## The Stack at a Glance

Before diving into the details, here's every component in the chain:

| Layer | Component | Role |
|-------|-----------|------|
| Music Server | Lyrion Music Server (LMS) | Central brain — indexes library, streams to players |
| Host | Synology NAS (Docker container) | Runs LMS 24/7 without dedicated hardware |
| Players | PiCorePlayer on Raspberry Pi 4 | Receives stream from LMS, outputs to WIIM |
| Display | 7" Raspberry Pi touchscreen | Control panel per Pi — browse and play |
| Power | PoE HAT on Raspberry Pi | Single ethernet cable per Pi — no power brick |
| Synchronization | WIIM Pro (×2) | Receives stream, feeds both amplifiers in sync |
| Amplifiers | AudioSource AD5012 (×2) | 12-channel Class D, drives all speaker zones |
| Zone control | OSD Audio SVC-300 (per zone) | In-wall volume knob per zone |
| In-ceiling speakers | Sonance MAG8R (8" 2-way) | Hi-res capable, 40Hz–20kHz, 90dB |
| Subwoofers | Sonance BPS8 (bandpass) | Low-end reinforcement, 35Hz–150Hz |
| Streaming | LMS plugins | Tidal, Spotify via built-in plugins |

## How It All Connects

```
                    ┌─────────────────────────────────┐
                    │         Synology NAS             │
                    │   ┌─────────────────────────┐   │
                    │   │  Lyrion Music Server     │   │
                    │   │     (Docker)             │   │
                    │   │  • Local hi-res library  │   │
                    │   │  • Tidal plugin          │   │
                    │   │  • Spotify plugin        │   │
                    │   └────────────┬────────────┘   │
                    └────────────────│─────────────────┘
                                     │ Network (LAN)
                    ┌────────────────┴─────────────────┐
                    │                                   │
          ┌─────────▼──────────┐           ┌───────────▼────────┐
          │  Raspberry Pi #1   │           │  Raspberry Pi #2   │
          │  (PoE powered)     │           │  (PoE powered)     │
          │  PiCorePlayer      │           │  PiCorePlayer      │
          │  7" Touchscreen    │           │  7" Touchscreen    │
          └─────────┬──────────┘           └───────────┬────────┘
                    │       Squeezebox protocol         │
                    └──────────────┬────────────────────┘
                                   │ (synchronized stream)
                          ┌────────┴────────┐
                          │                 │
               ┌──────────▼──────┐ ┌────────▼─────────┐
               │   WIIM Pro #1   │ │   WIIM Pro #2    │
               │  (analog out)   │ │  (analog out)    │
               └──────────┬──────┘ └────────┬─────────┘
                          │                 │
               ┌──────────▼──────┐ ┌────────▼─────────┐
               │  AudioSource    │ │  AudioSource     │
               │  AD5012 #1      │ │  AD5012 #2       │
               │  12-ch Class D  │ │  12-ch Class D   │
               └──┬──┬──┬──┬────┘ └──┬──┬──┬──┬──────┘
                  │  │  │  │         │  │  │  │
              Zone 1  2  3  4     Zone 4  5  ..
                  │  │  │  │         │  │  │
           ┌──────▼──┐ ┌▼─────┐   ┌──▼──┐ ┌▼──────┐
           │OSD SVC- │ │OSD   │   │OSD  │ │OSD    │
           │300 Vol  │ │SVC-  │   │SVC- │ │SVC-   │
           │Control  │ │300   │   │300  │ │300    │
           └──────┬──┘ └┬─────┘   └──┬──┘ └┬──────┘
                  │     │            │     │
            Sonance MAG8R          Sonance MAG8R
            + BPS8 subwoofer       + BPS8 subwoofer
```

The key design insight: **WIIM Pro handles synchronization, AudioSource AD5012 handles zones**. Both WIIM players receive the exact same synchronized audio stream from LMS. Each feeds one AD5012 amplifier. The AD5012's 12 channels then distribute that audio across the house — and the per-zone OSD volume controls let you independently adjust the level in each room without touching the amplifier or the software.


## Lyrion Music Server on Synology (Docker)

Lyrion Music Server (formerly Logitech Media Server) is the heart of the whole system. It runs as a Docker container on my Synology NAS, which means it runs 24/7 without spinning up a dedicated machine.

### Docker Compose Setup

```yaml
version: "3"
services:
  lyrion:
    image: lmscommunity/lyrionmusicserver:latest
    container_name: lyrion
    network_mode: host        # required for player discovery (mDNS/UDP broadcasts)
    volumes:
      - /volume1/docker/lyrion/config:/config
      - /volume1/music:/music:ro          # your music library (read-only)
      - /volume1/docker/lyrion/playlist:/playlist
    environment:
      - PUID=1026               # match your Synology user
      - PGID=100
      - TZ=America/Los_Angeles
    restart: unless-stopped
```

**Why `network_mode: host`?** LMS uses UDP broadcasts for player discovery. Bridge networking blocks these broadcasts, so players can't find the server. Host networking is the simplest fix.

Once the container is running, LMS is accessible at `http://your-nas-ip:9000`.

### LMS Web Interface

{{< figure src="/images/lms-dashboard.png" alt="Lyrion Music Server dashboard showing connected players and now playing" caption="LMS dashboard — all players visible, currently playing synchronized across zones" >}}

The dashboard shows every connected player, what's currently playing, and lets you group players for synchronized playback. The left sidebar gives you your full library — artists, albums, genres, playlists.

### Music Library Setup

Point LMS at your music folder during initial setup. It scans and indexes everything — album art, tags, the works. For a library of 10,000+ tracks the initial scan takes a few minutes; after that it monitors for changes automatically.

{{< figure src="/images/lms-library.png" alt="LMS library view showing albums and artists" caption="LMS library — album art pulled automatically from tags and online sources" >}}

## PiCorePlayer on Raspberry Pi

PiCorePlayer is a minimal Linux distribution purpose-built to run Squeezelite — the software Squeezebox client that connects to LMS. It boots from a small SD card, runs entirely in RAM, and is extremely stable. My Pis have been running for months without a reboot.

### Hardware Per Pi

- Raspberry Pi 4 (2GB or 4GB)
- PoE HAT — powers the Pi directly from the ethernet cable, no separate power supply
- Official 7" Raspberry Pi touchscreen
- MicroSD card (8GB is plenty — PiCorePlayer is tiny)

The PoE setup is the cleanest part of this build. One ethernet cable per Pi, plugged into a PoE switch. No power bricks, no cable management headaches. The Pi gets data and power over a single cable.

{{< figure src="/images/raspberry-pi-poe.jpg" alt="Raspberry Pi 4 with PoE HAT and 7-inch touchscreen mounted on wall" caption="Raspberry Pi 4 with PoE HAT and 7\" touchscreen — single ethernet cable handles both power and data" >}}

### PiCorePlayer Setup

Flash the PiCorePlayer image to the SD card (balenaEtcher works well), boot the Pi, and it auto-detects LMS on the network. The web interface at `http://pi-ip-address` gives you full configuration:

{{< figure src="/images/picore-main.png" alt="PiCorePlayer main web interface showing player settings" caption="PiCorePlayer web interface — configure audio output, player name, LMS connection" >}}

Key settings to configure:
- **Player name** — give each Pi a meaningful name (Kitchen, Hallway, etc.)
- **Audio output** — select the correct output device (HDMI, USB DAC, or 3.5mm)
- **LMS server** — usually auto-discovered; can be set manually by IP

### The Touchscreen

The 7" touchscreen runs Jivelite — the graphical front-end for Squeezebox players. It shows album art, track info, playback controls, and lets you browse your entire library by touch.

{{< figure src="/images/jivelite-nowplaying.png" alt="Jivelite now-playing screen on 7-inch touchscreen showing album art" caption="Jivelite on the 7\" display — album art, track info, and full playback controls by touch" >}}

This is what makes the system genuinely usable day-to-day. Instead of pulling out your phone to change a track, you tap the screen on the wall. The display also shows what's playing in every other zone and lets you switch between them.

## WIIM Pro: Synchronization Bridge

The two WIIM Pro players are the synchronization bridge in this system. They receive the hi-res audio stream from PiCorePlayer over the network and output analog audio to the amplifiers. The critical role they play is not zone management — that's handled by the amplifiers — but keeping both amplifiers perfectly locked to the same audio stream.

Both WIIM players are grouped in LMS and receive identical timing-synchronized streams. This is what makes music in the upstairs corridor match exactly what's playing in the kitchen — the amplifiers are fed the same signal at the same moment.

## AudioSource AD5012: 12-Channel Amplifier

Each WIIM Pro feeds one AudioSource AD5012 — a 12-channel Class D amplifier designed specifically for whole-house distributed audio. With two AD5012s in the setup, there are 24 amplified channels total, organized into the speaker zones throughout the house.

| Specification | Value |
|---------------|-------|
| Channels | 12 (6 stereo pairs) |
| Power output | 50W/channel @ 8Ω |
| Power output | 75W/channel @ 4Ω |
| Bridged mono | 125W @ 8Ω |
| Amplifier class | Class D (digital) |
| Frequency response | 20Hz – 20kHz ±0dB |
| THD+N | <0.2% |
| Signal-to-noise ratio | 100dB (A-weighted) |
| Channel separation | 65dB @ 1kHz |
| Inputs | 12× RCA line-in, 2× Bus RCA, 1× Optical PCM |
| Speaker terminals | Phoenix-style connectors |
| Power modes | On / Auto signal-sensing / 12V trigger |

The Class D design means the AD5012 runs cool and efficiently even with 12 channels active — important for a unit that's running 24/7 in a rack or closet. The optical PCM input is particularly useful: it accepts the digital signal directly, skipping an extra analog conversion stage.

### Speaker Zones

The 12 channels on each AD5012 are organized into stereo zones. The five whole-house zones, and what's in each:

| Zone | Rooms | Speakers |
|------|-------|----------|
| Zone 1 | Main Bedroom + Main Restroom | 4 speakers |
| Zone 2 | Upstairs Corridor + Stairs | 4 speakers |
| Zone 3 | Downstairs Corridor + Dining Room | 4 speakers (2 + 2) |
| Zone 4 | Kitchen | 4 speakers |
| Zone 5 | Living Room | 4 speakers |

Each zone draws 2 channels from an AD5012 (one stereo pair). With 20 speakers across 5 zones, the two AD5012s together cover the entire house.

## OSD Audio SVC-300: Per-Zone Volume Control

Volume in each zone is controlled independently using the OSD Audio SVC-300 in-wall volume control — one per zone, mounted in the wall like a light switch.

| Specification | Value |
|---------------|-------|
| Power handling | 300W peak / 150W RMS per channel |
| Frequency response | 20Hz – 20kHz |
| Attenuation range | 52dB (12-step rotary knob) |
| Impedance matching | 1, 2, 4, 6, or 8 speaker pairs |
| Wiring | Accepts up to 14-gauge wire |
| Enclosure | Standard single-gang wall box |
| Finish options | White, Ivory, Almond (included) |
| Warranty | 5 years |

The SVC-300 sits between the amplifier output and the speakers for each zone. Turning the knob attenuates the signal in 12 steps across 52dB of range — enough to go from full volume to nearly silent. The impedance matching feature matters when running multiple speakers per zone: it prevents the amplifier from seeing an impedance load that's too low.

The practical result: you can walk into the kitchen and turn the volume down without touching a phone, app, or the amplifier itself. Each room behaves independently even though all rooms are playing the same synchronized source.

### Synchronized Playback

This is the killer feature. In LMS, you select multiple players and group them:

{{< figure src="/images/lms-sync-groups.png" alt="LMS synchronization groups showing all three zones grouped together" caption="LMS player grouping — all three zones synchronized, music plays in perfect lockstep" >}}

Once grouped, LMS sends the same audio stream to all players with timing synchronization. Walk from the kitchen to the living room to the home theater — the music follows you with zero echo or delay between rooms. This is something proprietary whole-house audio systems charge thousands of dollars for.

## In-Ceiling Speakers: Sonance MAG Series

The speakers are the final link in the chain, and they're worth choosing carefully — especially when the rest of the system is capable of delivering hi-res audio. I use Sonance MAG series speakers throughout the house: the MAG8R for main in-ceiling coverage and the BPS8 bandpass subwoofer for low-end reinforcement.

### Sonance MAG8R — 8" 2-Way In-Ceiling Speaker

The MAG8R is an audiophile-grade in-ceiling speaker designed for high-fidelity music playback, not just background fill. The 8" woofer gives it enough cone area to reproduce lower midrange with real body, and the pivoting tweeter lets you aim the high-frequency dispersion toward the listening area rather than straight down at the floor.

| Specification | Value |
|---------------|-------|
| Driver configuration | 8" poly cone woofer + 1" pivoting silk dome tweeter |
| Frequency response | 40Hz – 20kHz |
| Sensitivity | 90dB (1W/1m) |
| Impedance | 8Ω |
| Power handling | 100W continuous |
| Crossover | Internal 2-way crossover |

The 90dB sensitivity means it produces 90dB of output from just 1 watt — efficient enough that the 12-channel amplifier doesn't have to work hard to reach comfortable listening levels. At hi-res listening volumes, these are genuinely musical speakers, not just "ceiling speakers."

### Sonance BPS8 — 8" Passive Bandpass In-Ceiling Subwoofer

The BPS8 is a bandpass subwoofer designed specifically for in-ceiling installation. The bandpass enclosure design filters the output to a tight low-frequency band — it only reproduces what a standard in-ceiling speaker can't: the real bottom end. This pairing is what makes hi-res playback of bass-heavy material (orchestral, electronic, jazz) feel physically present rather than just acoustically correct.

| Specification | Value |
|---------------|-------|
| Driver | 8" long-excursion woofer |
| Frequency response | 35Hz – 150Hz (bandpass filtered) |
| Sensitivity | 88dB (1W/1m) |
| Impedance | 8Ω |
| Power handling | 150W continuous |
| Design | Sealed bandpass enclosure, in-ceiling mount |

The BPS8 pairs with the 12-channel amplifier — two channels per subwoofer or one dedicated channel depending on your amplifier layout. The bandpass design means you don't need a crossover network: it naturally rolls off above 150Hz, handing off cleanly to the MAG8Rs for everything above that.

### Why This Speaker Choice Matters for Hi-Res

Most in-ceiling speakers are designed for speech intelligibility and background music. The MAG series is designed for music. The combination of the MAG8R's extended high-frequency response to 20kHz and the BPS8's low extension to 35Hz covers the full audible spectrum — the same range that hi-res recordings at 24-bit/192kHz actually contain information in.

Playing a 24-bit/192kHz FLAC through a system that caps at 16kHz and rolls off below 80Hz defeats the purpose of the entire chain above it. The Sonance MAG series is what makes the hi-res investment audible.

## Streaming Services: Tidal and Spotify

LMS has a plugin ecosystem, and the streaming service plugins are genuinely excellent. They appear as first-class library items inside LMS — no need to switch apps.

### Tidal

The Tidal plugin supports Tidal Connect as well as direct library integration. Hi-res FLAC streams if you have a Tidal HiFi subscription — and with the WIIM players handling DAC duties, you're actually getting the benefit of those high-resolution files.

### Spotify

The Spotify plugin works with Spotify Connect, so it shows up as a playback target in the Spotify app as well as being browsable from within LMS.

{{< figure src="/images/lms-spotify-tidal.png" alt="LMS Spotify and Tidal plugins showing streaming library integration" caption="Spotify and Tidal integrated into LMS — browse and play directly alongside your local library" >}}

### Installing Plugins

Both plugins install from the LMS plugin manager — no manual file copying needed:

1. In LMS web interface, go to **Settings → Plugins**
2. Search for the plugin by name
3. Click Install, restart LMS
4. Enter your service credentials in the plugin settings

{{< figure src="/images/lms-plugins.png" alt="LMS plugin manager showing installed streaming service plugins" caption="LMS plugin manager — streaming services install in seconds" >}}

## Hi-Res Audio: The Real Reason to Build This

This is the aspect that most whole-house audio comparisons gloss over, and it's the main reason I built this system instead of buying something off the shelf.

Proprietary systems like Sonos cap out at 24-bit/48kHz. That's CD-quality at best — fine, but not what you're getting from a high-resolution music library or a Tidal HiFi subscription streaming 24-bit/192kHz FLAC. The hardware is simply incapable of passing those files through at full quality.

This setup doesn't have that limitation.

### Lyrion Music Server: Full Hi-Res Passthrough

LMS serves audio files natively — it doesn't transcode or downsample unless you tell it to. What's on disk is what gets sent to the player:

| Format | Support |
|--------|---------|
| FLAC | Up to 32-bit / 384kHz |
| WAV / AIFF | Up to 32-bit / 384kHz |
| ALAC | Up to 24-bit / 192kHz |
| MP3, AAC, OGG | Standard lossy formats |
| DSD64 / DSD128 | Native DSD or DSD-over-PCM (DoP) |
| MQA | Via Tidal plugin (unfolds to 24-bit/96kHz) |

The key setting is in LMS under **Settings → Player → Audio**: ensure the output bitrate and sample rate are set to "keep original" rather than any fixed rate. LMS will then pass through whatever the source file contains, including gapless playback for albums where tracks run continuously.

### WIIM Pro: Hi-Res DAC

The WIIM Pro is certified for hi-res audio playback and handles the digital-to-analog conversion at the end of the chain:

| Capability | Specification |
|-----------|---------------|
| PCM playback | Up to 32-bit / 384kHz |
| DSD playback | DSD64 and DSD128 via DoP |
| Output | Optical (TOSLINK), coaxial S/PDIF, analog RCA |
| DAC chip | Supports 32-bit processing |
| Hi-Res certification | Hi-Res Audio certified |

The optical and coaxial outputs pass the digital signal directly to an external DAC or amplifier, letting you use your own DAC if you prefer. The analog RCA outputs use the WIIM's internal DAC — which is genuinely good for the price.

### The Full Chain at 24-bit/192kHz

```
FLAC file on NAS (24-bit/192kHz)
  → LMS (passes through unmodified)
    → PiCorePlayer / Squeezelite (no transcoding)
      → WIIM Pro (decodes, outputs 24-bit/192kHz)
        → Amplifier → Speakers
```

Every link in this chain is capable of handling the full resolution. Nothing throttles it.

Compare this to Sonos, which resamples everything to 16-bit/48kHz internally, or to Bluetooth streaming, which compresses the audio before it even leaves your phone. If you've spent money on a hi-res music library — whether purchased FLAC files or a Tidal HiFi subscription — this setup actually plays it at the quality you paid for.

## Network Setup

A few networking notes that make the difference between a smooth setup and a frustrating one:

**Use wired ethernet for the Pis** — PoE makes this easy anyway, but wired is important for audio. Wi-Fi dropouts cause buffer underruns which cause audio glitches. The Pis are wired; the WIIMs can be Wi-Fi since they have their own buffers.

**Static IPs or DHCP reservations** — Assign fixed IPs to the NAS and both Pis. LMS stores player configurations by IP. If a Pi gets a new IP after a DHCP lease renewal, LMS treats it as a new player.

**mDNS/Bonjour** — LMS and PiCorePlayer use mDNS for discovery. If you have a managed switch with IGMP snooping enabled aggressively, mDNS packets can get blocked. Either whitelist multicast or use manual IP configuration in PiCorePlayer if discovery isn't working.

**PoE switch** — I use a PoE+ switch (802.3at, 30W per port). The Pi 4 with PoE HAT draws around 10W under normal load, so standard PoE (802.3af, 15W) is usually fine, but PoE+ gives headroom for the display backlight.

## Cost Breakdown

| Component | Approximate Cost |
|-----------|-----------------|
| Synology NAS (already owned) | $0 incremental |
| Raspberry Pi 4 (×2) | ~$70 each |
| PoE HAT (×2) | ~$20 each |
| 7" touchscreen (×2) | ~$80 each |
| WIIM Pro (×2) | ~$80 each |
| AudioSource AD5012 (×2) | ~$400 each |
| OSD Audio SVC-300 volume control (×5) | ~$40 each |
| Sonance MAG8R in-ceiling speakers | Varies by room count |
| Sonance BPS8 bandpass subwoofers | Varies by room count |
| **Software** | **$0** |

The software stack — LMS, PiCorePlayer, Jivelite — is completely free and open source. The streaming service plugins are maintained by the community. You pay for the streaming subscriptions themselves (Tidal, Spotify), but those are the same subscriptions you'd pay regardless.

Compare this to a Sonos whole-house setup for the same number of zones and speaker count: you're looking at $2,000+ just for the Sonos hardware, plus the ongoing risk of a company deciding to brick older hardware or change their subscription model. With this setup, the software will keep working as long as the hardware does.

## What Works Really Well

**Full hi-res audio, end to end.** This is the reason to build this over any proprietary system. LMS passes FLAC files through unmodified — 24-bit/192kHz stays 24-bit/192kHz. WIIM Pro decodes it at full quality. Nothing in the chain caps or resamples. If you have a hi-res library, you actually hear it.

**Synchronization is flawless.** Walk through the house and the music is perfectly in step everywhere. No echo, no delay. This is the hardest thing to get right and LMS has solved it for 20 years.

**The touchscreen is underrated.** Having a physical display with album art and touch controls in each zone is significantly more convenient than a phone app, especially when hands are occupied in the kitchen.

**PoE simplifies everything.** Ethernet was going to those locations anyway for networking. Getting power from the same cable means no searching for outlets, no visible power bricks.

**Plugin ecosystem is mature.** LMS has been around since the early 2000s. The plugin ecosystem is extensive — internet radio stations, podcast support, streaming services, audio DSP plugins. It's well beyond just playing local files.

## What to Watch Out For

**Initial LMS setup has a learning curve.** The web interface is functional but not modern-looking. Don't let the dated UI put you off — the functionality underneath is excellent.

**PiCorePlayer SD card wear.** PiCorePlayer runs in RAM and saves configuration changes to the SD card periodically. Use a quality SD card (Samsung Endurance series are good for this) and it'll last for years.

**WIIM firmware updates occasionally reset settings.** Keep a note of your WIIM audio output settings. After a firmware update, the output level or format settings occasionally reset to defaults.

**Network discovery can be finicky.** If LMS can't find your players on first setup, check that you're using `network_mode: host` in Docker and that your switch isn't blocking multicast. Manual IP entry in PiCorePlayer always works as a fallback.

## Summary

This setup has been running reliably for over a year. The combination of LMS's rock-solid synchronization engine, PiCorePlayer's stability, and WIIM's clean analog output hits a sweet spot of performance, flexibility, and cost that proprietary systems can't match.

The whole stack is self-hosted and open-source at its core. No cloud dependency, no subscription to a hardware ecosystem, no risk of the manufacturer deciding your hardware is obsolete. The music plays as long as the hardware runs — which, for a Raspberry Pi and a NAS, is a very long time.

If you're building something similar or have questions about any part of the setup, the [Lyrion community forums](https://forums.lyrion.org) are excellent — active, knowledgeable, and welcoming to new setups.
