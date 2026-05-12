---
title: "Whole House Audio with Lyrion Music Server, PiCorePlayer, and WIIM"
date: 2024-12-10
tags: ["homelab", "audio", "raspberry-pi", "docker", "synology", "lyrion", "self-hosted"]
description: "How I built a whole-house synchronized audio system using Lyrion Music Server on Synology NAS, PiCorePlayer on Raspberry Pi, and WIIM amplifiers — with Apple Music, Tidal, and Spotify support built in."
---

When I started thinking about whole-house audio, I had two requirements: the music had to be perfectly synchronized across every room, and I didn't want a subscription lock-in to some proprietary ecosystem. What I ended up with is a fully self-hosted setup built around open-source software, a few Raspberry Pis, and WIIM amplifiers — and it sounds fantastic.

This post walks through the complete architecture, how everything connects, and how I stream from Apple Music, Tidal, and Spotify on top of my local music library.

## The Stack at a Glance

Before diving into the details, here's every component in the chain:

| Layer | Component | Role |
|-------|-----------|------|
| Music Server | Lyrion Music Server (LMS) | Central brain — indexes library, streams to players |
| Host | Synology NAS (Docker container) | Runs LMS 24/7 without dedicated hardware |
| Players | PiCorePlayer on Raspberry Pi 4 | Receives stream from LMS, outputs to WIIM |
| Display | 7" Raspberry Pi touchscreen | Control panel per Pi — browse and play |
| Power | PoE HAT on Raspberry Pi | Single ethernet cable per Pi — no power brick |
| Amplifiers | WIIM Pro + 12-channel amp | Drives all in-ceiling/in-wall speakers |
| Zones | WIIM Pro (living room + home theater) | Stereo zones with synchronized playback |
| Streaming | LMS plugins | Apple Music, Tidal, Spotify via built-in plugins |

## How It All Connects

```
                    ┌─────────────────────────────────┐
                    │         Synology NAS             │
                    │   ┌─────────────────────────┐   │
                    │   │  Lyrion Music Server     │   │
                    │   │     (Docker)             │   │
                    │   │                          │   │
                    │   │  • Local music library   │   │
                    │   │  • Apple Music plugin    │   │
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
                    │                                   │
                    │         Squeezecast/UPnP          │
                    └──────────────┬────────────────────┘
                                   │
              ┌────────────────────┼───────────────────┐
              │                    │                   │
    ┌─────────▼──────┐   ┌─────────▼──────┐   ┌───────▼────────┐
    │  WIIM Pro      │   │  WIIM Pro      │   │  WIIM Pro      │
    │  (Whole House) │   │  (Living Room) │   │  (Home Theater)│
    └────────┬───────┘   └───────┬────────┘   └───────┬────────┘
             │                   │                    │
    ┌────────▼───────┐   ┌───────▼────────┐   ┌──────▼─────────┐
    │ 12-Channel Amp │   │  Stereo Amp    │   │  Stereo Amp    │
    └────────┬───────┘   └───────┬────────┘   └──────┬─────────┘
             │                   │                    │
    ┌────────▼───────┐   ┌───────▼────────┐   ┌──────▼─────────┐
    │ In-ceiling &   │   │  Living Room   │   │  Home Theater  │
    │ in-wall spkrs  │   │  Speakers      │   │  Speakers      │
    │ (whole house)  │   │                │   │                │
    └────────────────┘   └────────────────┘   └────────────────┘
```

The key insight in this architecture: **PiCorePlayer acts as a Squeezebox client**. It connects to LMS over the network, receives the audio stream, and forwards it to the WIIM player. The WIIM then handles the actual digital-to-analog conversion and feeds the amplifier. Every device that LMS knows about can be synchronized to play the same audio at exactly the same time — no drift, no echo between rooms.

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

## WIIM Players and Amplifiers

The WIIM Pro players are where the audio leaves the digital realm. Each WIIM receives the audio stream from PiCorePlayer (via UPnP/AirPlay or direct Squeezebox protocol) and outputs analog audio to the connected amplifier.

### Zone Breakdown

**Whole-House Zone** — WIIM Pro connected to a 12-channel amplifier. This drives in-ceiling and in-wall speakers throughout the house — kitchen, hallways, bedrooms, outdoor areas. All channels play the same audio simultaneously.

**Living Room Zone** — Dedicated WIIM Pro into a stereo amplifier driving the living room speakers. Separate zone means I can play something different here when entertaining, or lock it to the whole-house sync.

**Home Theater Zone** — Third WIIM Pro into the home theater receiver/amplifier. When I want background music while watching something, it's its own zone. When I want the whole house in sync, I group it with the others in LMS.

### Synchronized Playback

This is the killer feature. In LMS, you select multiple players and group them:

{{< figure src="/images/lms-sync-groups.png" alt="LMS synchronization groups showing all three zones grouped together" caption="LMS player grouping — all three zones synchronized, music plays in perfect lockstep" >}}

Once grouped, LMS sends the same audio stream to all players with timing synchronization. Walk from the kitchen to the living room to the home theater — the music follows you with zero echo or delay between rooms. This is something proprietary whole-house audio systems charge thousands of dollars for.

## Streaming Services: Apple Music, Tidal, Spotify

LMS has a plugin ecosystem, and the streaming service plugins are genuinely excellent. They appear as first-class library items inside LMS — no need to switch apps.

### Apple Music

The Apple Music plugin for LMS uses your Apple Music subscription to stream directly through LMS to all your players. Your playlists, library, and recommendations all show up in the LMS interface.

{{< figure src="/images/lms-apple-music.png" alt="LMS interface showing Apple Music playlists and albums" caption="Apple Music fully integrated into LMS — playlists and library browsable alongside local music" >}}

### Tidal

The Tidal plugin supports Tidal Connect as well as direct library integration. Hi-res FLAC streams if you have a Tidal HiFi subscription — and with the WIIM players handling DAC duties, you're actually getting the benefit of those high-resolution files.

{{< figure src="/images/lms-tidal.png" alt="LMS Tidal plugin showing Tidal library and new releases" caption="Tidal integrated into LMS — hi-res streams available end-to-end" >}}

### Spotify

The Spotify plugin works with Spotify Connect, so it shows up as a playback target in the Spotify app as well as being browsable from within LMS.

{{< figure src="/images/lms-spotify.png" alt="LMS Spotify plugin" caption="Spotify via LMS plugin — browse and play directly from the LMS interface" >}}

### Installing Plugins

All three plugins install from the LMS plugin manager — no manual file copying needed:

1. In LMS web interface, go to **Settings → Plugins**
2. Search for the plugin by name
3. Click Install, restart LMS
4. Enter your service credentials in the plugin settings

{{< figure src="/images/lms-plugins.png" alt="LMS plugin manager showing installed streaming service plugins" caption="LMS plugin manager — streaming services install in seconds" >}}

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
| WIIM Pro (×3) | ~$80 each |
| 12-channel amplifier | ~$300 |
| Stereo amplifiers (×2) | ~$100 each |
| In-ceiling/in-wall speakers | Varies |
| **Software** | **$0** |

The software stack — LMS, PiCorePlayer, Jivelite — is completely free and open source. The streaming service plugins are maintained by the community. You pay for the streaming subscriptions themselves (Apple Music, Tidal, Spotify), but those are the same subscriptions you'd pay regardless.

Compare this to a Sonos whole-house setup for the same number of zones and speaker count: you're looking at $2,000+ just for the Sonos hardware, plus the ongoing risk of a company deciding to brick older hardware or change their subscription model. With this setup, the software will keep working as long as the hardware does.

## What Works Really Well

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
