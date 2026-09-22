# arib_caption_mux.py — manual
<p align="center"><img alt="Да, Господин Кальмар!" src="https://github.com/andruxaster/ARIB-captions-muxer/blob/main/6fba3bbd4188c2c2.png?raw=true" /></p>

The script builds an MPEG-2 Transport Stream that a Japanese D-VHS deck
accepts as a digital broadcast recording: ARIB STD-B24 captions, AAC audio,
service information tables and copy-control flags.

Tested on Victor decks -- HM-DH30000, HM-DHX1 and HM-DHS1 -- and against an
off-air capture from BS Nittele. Victor is the Japanese domestic brand; the
same machines were sold as JVC everywhere else, and the Japanese ones matter
here because they carry the ARIB caption decoder.

Two facts about that hardware shape the advice below:

* **Captions are displayed only by the HM-DH30000.** The other decks record
  and replay the caption ES faithfully, they simply do not render it.
* **The HM-DH30000 records only in HS.** Ask it for STD or LS3 and it
  re-encodes the stream itself; the captions survive that, verified by
  experiment. So when that deck is the target there is no point squeezing the
  stream into the 14.1 Mbit/s of STD -- feed it HS and let it transcode.

- [1. How it works](#1-how-it-works)
- [2. Installation](#2-installation)
- [3. First run](#3-first-run)
- [4. Subtitles](#4-subtitles)
- [5. Latin, Cyrillic and the caption area](#5-latin-cyrillic-and-the-caption-area)
- [6. ASS files](#6-ass-files)
- [7. Audio](#7-audio)
- [8. Service information](#8-service-information)
- [8.8. D-Theater tape mode](#88-d-theater-tape-mode)
- [9. Copy-control flags](#9-copy-control-flags)
- [10. Timing](#10-timing)
- [11. Bit rate and D-VHS modes](#11-bit-rate-and-d-vhs-modes)
- [12. Ready-made recipes](#12-ready-made-recipes)
- [13. Checking the result](#13-checking-the-result)
- [14. Troubleshooting](#14-troubleshooting)
- [15. Every option](#15-every-option)
- [Glossary](#glossary)

---

## 1. How it works

### 1.1. Why this is needed at all

A D-VHS deck does not encode video. It writes to tape the finished transport
stream that a tuner hands it over i.LINK. So to get your own material onto
tape you have to build a stream indistinguishable from a broadcast one — both
in the caption format and in the service information.

The script does exactly the inverse of what
[libaribcaption](https://github.com/xqq/libaribcaption) does: that library
decodes ARIB captions, this one composes them.

### 1.2. How ARIB captions are built

Unlike SRT, which carries only text and timing, ARIB STD-B24 is a **stream of
drawing commands**. Every cue travels as a sequence of bytes the receiver
executes: set the plane size, set the area, place the cursor, pick a colour,
emit glyphs.

Text is encoded with an 8-unit code that switches between sets:

| Set | Contents | Invoked by |
|---|---|---|
| Kanji (G0) | JIS X 0208: ideographs, kana, Cyrillic, Greek | `LS0` |
| Alphanumeric (G1) | half-width Latin letters and digits | `LS1` |
| DRCS | bitmaps for glyphs missing from the sets | `ESC 2/10` |

Cyrillic sits in row 7 of JIS X 0208, so Russian text encodes natively with
no tricks. Guillemets and the Ukrainian letters are not there — see
section 5.

### 1.3. Screen geometry

The script reproduces the layout Japanese broadcasters use:

```
plane 960 x 540                      (SWF 7)
    caption area 620 x 480 at (170, 30)          (SDF/SDP)
        glyph 36 x 36, spacing 4, line spacing 24    (SSM/SHS/SVS)
            -> cell of 40 x 60 dots
            -> 15 full-width glyphs per row, up to 8 rows
```

A full-width glyph (an ideograph, or Cyrillic in normal mode) takes a whole
cell; a half-width glyph (Latin, digits, or Cyrillic in `half` mode) takes
half of one. Hence the limit of 15 or 30 glyphs per row.

### 1.4. Positioning: APS versus ACPS

This is where the script deliberately departs from a real broadcaster.

- **ACPS** gives the position in dots. That is what a BS broadcaster sends.
- **APS** gives a row and a column in cells.

The trouble is that receivers disagree about the origin of ACPS coordinates.
libaribcaption counts from the corner of the screen, while a Victor HM-DH30000
counts from the corner of the caption area, that is with an offset of
(170, 30). Sent through ACPS, rows drifted right and down, hit the edge and
wrapped around into the top-left corner.

So **APS is the default**: nothing is ambiguous about it. `--positioning acps`
restores the old behaviour if you want byte-level similarity with broadcast.

### 1.5. How the stream reaches the tape

A tuner hands the deck not the full broadcast multiplex but a **partial TS**
per ARIB STD-B21: one programme, without the other channels and without most
of the service information. In their place comes the SIT, which describes
what exactly was recorded. That is the default mode (`--si partial`).

```
input: full broadcast TS            output: partial TS
+----------------------+           +----------------------+
| PAT (many programmes)|           | PAT (one programme)  |
| PMT of service 171   |           | PMT plus caption ES  |
| PMT of services 172-3|  ------>  | video, audio, PCR    |
| NIT SDT EIT TOT BIT  |           | SIT (once a second)  |
| ECM, SDTT, null      |           | DIT (at splices)     |
| video, audio, data   |           +----------------------+
+----------------------+
```

---

## 2. Installation

You need **Python 3.8+**. Everything else is optional:

| Program | What for | Without it |
|---|---|---|
| `ffmpeg` | audio encoding, reading non-WAV input | audio can be supplied as a ready `.aac`/`.mp2` |
| `fdkaac` | AAC with CRC in the ADTS, as on air | ffmpeg makes AAC without CRC |
| Pillow | `--drcs-font` | glyphs outside the sets become the geta mark |

```bash
# Debian/Ubuntu
sudo apt install python3 ffmpeg fdkaac python3-pil
```

To check that `ffmpeg` was built with libtwolame (the better MP2 encoder):

```bash
ffmpeg -hide_banner -encoders | grep twolame
```

---

## 3. First run

### 3.1. See what is inside a file

```bash
python3 arib_caption_mux.py sample.m2t --list
```

```
transport_stream_id: 0x4012, network_id: 0x0004
  NIT PID 0x0010
  service 171 (PMT 0x01F0)
    PCR PID 0x01FF
    PID 0x0100  MPEG-2 video     tag 0x00
    PID 0x0110  AAC              tag 0x10
    PID 0x0130  PES private      tag 0x30  [ARIB captions]
  copy control of service 171:
    digital_copy_control (0xC1) = 0x84 (10000100)
        digital_recording_control_data = 10  copy one generation
```

This is always worth starting with: it shows the services, the PIDs, whether
captions are already present and what the copy-control flags say.

### 3.2. The simplest build

```bash
python3 arib_caption_mux.py input.m2t subs.srt -o output.m2t
```

The script takes the first service that has video, inserts the captions as a
separate ES and rebuilds the stream as a partial TS.

---

## 4. Subtitles

### 4.1. The SRT format

Plain SRT in UTF-8. Supported:

```srt
1
00:00:01,000 --> 00:00:04,500
An ordinary cue,
two rows

2
00:00:05,000 --> 00:00:08,000
<font color="yellow">A coloured cue</font>

3
00:00:09,000 --> 00:00:12,000
{\an8}A cue at the top of the screen
```

Colour is mapped onto the eight ARIB colours: black, red, green, yellow,
blue, magenta, cyan, white. Both names (`yellow`) and hex codes (`#ff4040`)
are accepted.

### 4.2. Several tracks

You may pass several subtitle files. By default they are laid out the way
broadcast does it: **one ES with the languages told apart inside it** by the
`data_group_id` field — caption 1, caption 2. That is what the caption button
on the receiver switches between.

One ES carries at most two languages. If you pass more tracks, the extra ones
are dropped with a warning.

`--caption-multi es` puts every track into its own ES with its own
component_tag (0x30, 0x31...). The standard permits that too, but **real
decks do not show it**: verified on a Victor HM-DH30000, only the first track
appears. The mode is kept for software players.

```bash
python3 arib_caption_mux.py in.m2t ru.ass jp.srt -o out.m2t \
    --caption-lang rus,jpn --offset 0,-0.5
```

Per-track parameters are comma-separated lists; if you give fewer values than
tracks, the last one repeats.

| Option | Meaning |
|---|---|
| `--caption-lang rus,jpn` | ISO 639-2 languages |
| `--caption-multi lang` \| `es` | one ES with languages (default) or separate ES |
| `--offset 0,-0.5` | time offset, seconds |
| `--caption-pid 0x130,0x131` | PIDs by hand |

### 4.3. When the stream already carries captions

By default (`--existing replace`) the new tracks take over the broadcast ones
in order, inheriting their PIDs and tags. The language in the SIT and EIT
descriptors is rewritten to the new track's language.

`--existing keep` leaves the broadcast captions alone and adds the new ones
as further ES.

### 4.4. The language code is not just a label

You would think `--caption-lang` only labels the track. In fact, per ARIB,
the language code tells the receiver **which text encoding to expect**:

| Code | What the receiver switches to |
|---|---|
| `jpn` and most others | the JIS sets — what the script encodes |
| `eng`, `tgl` | UTF-8 parsing |
| `por`, `spa` | the ABNT Latin sets |

By default the script encodes in JIS, so with `eng` the receiver reads the
bytes as UTF-8 and shows garbage. There are two ways out.

**The safe one: `--caption-lang jpn`.** Latin text comes out of the JIS sets
perfectly well, and the language code does not affect the picture — it only
labels the track in the receiver's menu. This works on any Japanese receiver
because it is exactly what broadcast does.

**The honest one: `--encoding utf8`.** The management packet then carries
TCS = 1 (UCS mode), the text is encoded as UTF-8, and the C1 codes travel as
`0xC2` plus the code, as the standard requires.

The TCS field outranks the language code: the receiver looks at it first and
only guesses from the language when it is 0. So in `utf8` mode any language
code works — `eng`, `rus`, `jpn` and anything else. Verified on
libaribcaption: with TCS = 1 all four give the same correct text.

Example:

```bash
python3 arib_caption_mux.py in.m2t subs.srt -o out.m2t \
    --encoding utf8 --caption-lang eng
```

A side benefit: UCS has no character-set limits. Guillemets, low quotes, the
Ukrainian letters, Japanese and Latin in one row — everything comes out
directly, and DRCS is not needed.

| | `--encoding jis` | `--encoding utf8` |
|---|---|---|
| Encoding | ARIB sets (JIS X 0208) | UTF-8, TCS = 1 |
| Glyphs outside JIS | substitutions or DRCS | direct |
| `--caption-lang eng` | garbage | works |
| Other language codes | `jpn` and most are fine | any |
| Support by Japanese decks | as in broadcast | **not verified** |

That last row matters. UCS mode is in the standard, but Japanese broadcast
never uses it, so a deck may well not understand it. Only tested on
libaribcaption. If the deck shows a blank screen, go back to
`--encoding jis --caption-lang jpn`.

### 4.5. Line wrapping

Japanese text wraps by glyph with the kinsoku rules: characters like the
ideographic comma and full stop never start a row, and an opening bracket
never ends one. Alphabetic text (Russian, Latin) wraps **only at spaces**;
words are never split. Rows are balanced in length so you do not end up with
a long row followed by two words.

---

## 5. Latin, Cyrillic and the caption area

### 5.1. Latin

Latin letters, digits and punctuation are **always output at half width**
(the MSZ size); no option is needed for that. Thirty-one of them fit on a row.

They look widely spaced, and that is not a bug: the receiver's font is
monospaced, every letter occupies a full half cell, so narrow letters such as
"i" and "l" leave big gaps. Latin looks the same in real Japanese broadcast.

If the rows are too short, widen the caption area (see 5.4).

In `--encoding utf8` mode the widths are the same: ASCII and Cyrillic go at
half width, East Asian wide characters take a full cell.

### 5.2. Two width modes for Cyrillic

```bash
--cyrillic full    # default: 15 letters per row
--cyrillic half    # 30 letters per row
```

In `full` mode Cyrillic takes a whole cell, like an ideograph. It looks like
broadcast, but the rows are short: an average 32-character cue needs three
rows.

In `half` mode the letters go at half width and the receiver squeezes the
glyphs. Thirty characters fit on a row, which is usually more convenient for
Russian anime subtitles. The downside is that squeezed letters read worse in
the deck's font.

### 5.3. Glyphs missing from JIS X 0208

Cyrillic is there, but guillemets, low quotes, the Ukrainian letters and the
Belarusian short u are not. Two ways round it:

**Substitutions** (the default, nothing to do):

| From | To |
|---|---|
| « » | double angle brackets |
| low quotes | curly quotes |
| single guillemets | angle brackets |
| Ukrainian i | Latin i |
| the remaining Ukrainian and Belarusian letters | the geta mark, with a warning |

**DRCS** — the glyph is drawn as a bitmap inside the stream, by exactly the
mechanism a broadcaster uses for its own special symbols:

```bash
--drcs-font auto                        # find a system font with Cyrillic
--drcs-font /path/to/PTSans-Bold.ttf    # or name your own
```

Needs Pillow. Glyphs are drawn 36x36 in four brightness levels, which gives
real guillemets and Ukrainian letters. The limit is 94 distinct glyphs per
cue.

### 5.4. The caption area

By default the area copies the broadcast one: 620x480 from (170, 30), that is
31 half cells — 15 ideographs or 31 Latin letters per row. For English and
Russian subtitles that is cramped.

```bash
--area 880x480+40+30     # 44 characters per row instead of 31
```

The format is `WxH+X+Y` inside the 960x540 plane. Width is rounded to 20
dots, height to 60. The script prints the resulting limit:

```
captions: PID 0x0130 tag 0x30 eng; area 880x480+40+30, up to 44 glyphs per row
```

The difference on a 62-character cue:

| Area | Layout |
|---|---|
| 620x480+170+30 | 3 rows: 21 + 20 + 21 |
| 880x480+40+30 | 2 rows: 26 + 36 |

Bear in mind that the wider the area, the closer the text sits to the edge of
the frame, and decks and televisions crop part of it. 880 dots out of 960 is
about 92 % of the width, still safe; beyond that, check on your own screen.

---

## 6. ASS files

### 6.1. What is carried over and what is not

ASS is far richer than ARIB. What ARIB has is carried over:

| Carried over | Skipped |
|---|---|
| text, `\N`, `\h` | drawings `\p1` |
| alignment `\an`, `\a`, margins | rotation `\frz` `\frx` `\fry` |
| position `\pos` (for `\move`, the start point) | scaling `\fscx` `\fscy`, shear `\fax` |
| primary colour `\c` `\1c` `\r` -> 8 colours | animation `\t`, fades `\fad` |
| size `\fs` -> normal or small | border, shadow, blur, `\clip` |
| an alpha of `\alpha` = FF -> not shown | fonts `\fn`, bold, italic |
| wrapping `\q2` | karaoke `\k`, the Effect field |

The script prints a summary: how many events were skipped and which tags were
ignored.

### 6.2. Composing the screen

ARIB shows one whole screen at a time, not independent signs. Therefore:

- simultaneous events are composed onto **one screen** without overlaps;
- per-frame duplicated signs (tracking an object) are **collapsed** into a
  single static one;
- the lines of one sign are grouped into a **block**, ordered with the `\frz`
  rotation taken into account.

### 6.3. Dialogue only

If you want the dialogue without signs and karaoke:

```bash
python3 arib_caption_mux.py in.m2t episode.ass -o out.m2t --ass-dialogue-only
```

The decision is made in two stages.

**A style is dropped** if its name speaks of signs or songs (`Signs`,
`FrierenSigns`, `OP-Romaji`, `ED`, `Karaoke`, `Notes`, `Title`), or if plain
text makes up less than 70 % of it — unless there are 20 or more plain lines
and they make up at least 40 %.

**An event is dropped** even inside a dialogue style if it carries `\pos`
away from the style's own anchor, `\move`, `\k`, `\clip`, `\org`, rotation,
shear, a drawing, an fx Effect field or a "sign" Name field.

To see the verdict before building:

```bash
python3 arib_caption_mux.py in.m2t episode.ass -o x --ass-list-styles
```

```
Style                  events   plain  verdict   reason / sample
SubBN                     305    100%  dialogue  plain text 100%  "Do not overcomplicate..."
FrierenSigns              288      0%  skipped   by name: signs
opmieruko                 240      0%  skipped   signs: drawings in 100% of events
SentaiFont                144      0%  skipped   signs: \pos in 100% of events
```

If the heuristic gets it wrong, override it:

```bash
--ass-only-styles Default,Italics     # only these styles
--ass-skip-styles Songs,Notes         # never these
```

### 6.4. Other ASS options

| Option | Meaning |
|---|---|
| `--ass-signs place` | signs stay where they are (default) |
| `--ass-signs top` | every sign goes to the top of the screen |
| `--ass-signs skip` | signs are not shown |
| `--ass-small ssz` | small text in the small ARIB size (default) |
| `--ass-small normal` | small text in the normal size |
| `--ass-min-duration 0.3` | shorter screens merge into the previous one |

A note on `--ass-small ssz`: the small size in ARIB is meant for ruby text,
so libaribcaption and ffmpeg in text mode do not print such rows although
they do draw them in a picture. If you check the result with those tools and
the small text seems to have vanished, that is why.

---

## 7. Audio

### 7.1. Why replace the audio

Japanese broadcast audio is AAC. If the source carries AC-3, MP3 or MP2, a
Japanese deck will not play it. The script encodes the audio to MPEG-2 AAC-LC
48 kHz and packs it the way a broadcaster does: PES of 736 bytes, exactly
four TS packets, with a PTS on those PES where a frame starts.

### 7.2. One track

```bash
python3 arib_caption_mux.py in.m2t subs.srt -o out.m2t --audio dub.wav
```

WAV, FLAC and anything ffmpeg can read are accepted, as are ready-made `.aac`
(ADTS), `.mp2`, `.mpa` and `.m2a` files.

### 7.3. Several tracks

```bash
python3 arib_caption_mux.py in.m2t subs.ass -o out.m2t \
    --audio jp.wav --audio en.wav \
    --audio-lang jpn,eng --audio-name "Japanese" --audio-name "English" \
    --audio-bitrate 256,192
```

Tracks keep the order you gave, with component_tag 0x10, 0x11 and so on. The
first is the main component. Languages and names go into the EIT and SIT
descriptors.

The PID of the first track defaults to that of the audio it replaces (the
original AC-3 in the example above); the rest get free ones. With
`--arib-pids` the numbering becomes the broadcast one: 0x0110, 0x0111 and up.

`--keep-audio` leaves the source audio in place and appends the new tracks
after it.

### 7.4. 5.1

```bash
--audio surround.wav --audio-channels 6 --audio-bitrate 384
```

The channel count defaults to whatever the WAV has (1, 2 or 6). For 5.1 the
descriptor gets type 0x09, which is 3/2+LFE in ARIB terms. Channel order is
preserved with no reshuffling (verified by running a different tone through
each channel). Default bit rates are 384 kbit/s for 5.1, 256 for stereo and
144 for mono.

### 7.5. MP2 for decks from other makers

Decks that grew out of DVB rather than ISDB expect MPEG audio, not AAC. The
usual build carries both tracks:

```bash
python3 arib_caption_mux.py in.m2t subs.ass -o out.m2t \
    --audio jp.wav --audio-mp2 jp.wav
```

The first goes out as AAC (stream_type 0x0F) for Japanese decks, the second
as MPEG-1 Layer II (stream_type 0x03) for the rest.

Layer II is never multichannel: 5.1 in such a track is downmixed to stereo.
The bit-rate ceiling is 384 kbit/s for stereo and 192 for mono.

### 7.6. Dolby Digital (AC-3), the audio of D-Theater tapes

Commercial D-Theater tapes shipped with Dolby Digital: the sleeve typically
lists "English (5.1 Surround)" and "English (Stereo)".

```bash
python3 arib_caption_mux.py my.m2t -o out.m2t \
    --audio-ac3 surround.wav --audio-ac3 stereo.wav \
    --audio-lang eng,eng --audio-name "English 5.1" --audio-name "English Stereo"
```

The PMT gets `stream_type` 0x81 and the PES `stream_id` 0xBD. The standard
demands 48 kHz and no more than 640 kbit/s; mode 1+1 is forbidden. Defaults
are 576 kbit/s for 5.1 (as on tapes), 192 for stereo and 96 for mono. A
ready-made `.ac3` is taken as it is.

Verified on hardware: the Victor HM-DHX1 and HM-DH30000 both play AC-3 and
MP2 as well as AAC, even though Japanese broadcast uses only AAC.

### 7.7. DTS

Some D-Theater tapes carry DTS instead of, or alongside, Dolby Digital.

```bash
--audio-dts surround.wav
```

The PMT gets `stream_type` 0x82 with a `DTS ` registration descriptor (the
identifier is padded with a space) and the PES `stream_id` 0xBD. The standard
demands 48 kHz, frames of 512 samples and a constant bit rate between
188.25 and 1509.75 kbit/s; mode 1+1 is not among the listed ones. Defaults
are 1509.75 kbit/s for 5.1 (as on tapes), 768 for stereo and 384 for mono. A
ready-made `.dts` is taken as it is.

ffmpeg's DTS encoder is marked experimental, so the script passes
`-strict -2` for it.

A word of warning about hardware: none of the Victor decks here decodes DTS.
The DHX2 could pass it out over the optical output as a bitstream, nothing
more. So a DTS track is worth adding only to reproduce a tape faithfully, or
for an external decoder -- not for listening through the deck.

### 7.8. Linear PCM (SMPTE 302M)

Besides compressed audio the D-VHS standard allows linear PCM. That is what a
deck writes in its own STD recordings, and it is also found on D-Theater
tapes.

```bash
--audio-pcm dub.wav
```

Always 48 kHz, 16-bit, stereo — the standard permits nothing else. The PMT
gets `stream_type` 0x83 and the PES `stream_id` 0xBD, one chunk per 33 ms
(one video frame). The stream takes 1.54 Mbit/s, noticeably more than AAC,
which is worth remembering for STD and its 14.1 Mbit/s ceiling.

**Bit order.** In the 20-bit SMPTE 302M field four bits are status and
sixteen are audio. A deck and ffmpeg lay them out in opposite orders: the
deck puts the status bits first, ffmpeg puts them last. Worked out from a
deck recording: parsed the deck's way, the audio matches the MP2 track of the
same file with a correlation of 0.98; parsed ffmpeg's way it is noise.

By default the script writes the deck's order. `--pcm-bit-order ffmpeg`
switches to the other one — such a file is read correctly by ffmpeg and
software players, but probably not by a deck.

### 7.9. What the D-VHS standard demands of audio

Annex A.2.8 of IEC 60774-5 (BS EN 60774-5:2004) lists the audio a deck must
accept. The script checks the tracks against those points and warns about
violations:

| Requirement | How it is met |
|---|---|
| AAC of the LC profile only | LC is what we encode |
| Sample rate 32, 44.1 or 48 kHz | 48 kHz by default |
| CRC mandatory in the stream | fdkaac for AAC, `-error_protection` for MP2 |
| `adts_buffer_fullness` not 0x7FF | fdkaac writes a sane value |
| One `raw_data_block` per frame | that is what we do |
| AAC no more than 288 kbit/s per channel | 256 stereo, 384 for 5.1, with room to spare |
| Multichannel AAC up to 3/2+LFE | 5.1 explicitly allowed |
| Layer II up to 384 kbit/s | the ceiling is checked |
| AC-3 up to 640 kbit/s, no mode 1+1 | checked |
| DTS 48 kHz, 512-sample frames, 188.25-1509.75 kbit/s | checked |

Two of those were being violated before the standard turned up: MP2 was
encoded without CRC, and ffmpeg's AAC additionally sets
`adts_buffer_fullness` to 0x7FF, which the standard forbids. MP2 now always
carries CRC, and the script warns about ffmpeg's AAC — one more reason to
install fdkaac.

### 7.10. Encoder delay

Every encoder adds delay: the decoded audio comes out later than the source.
Ignore it and the audio drifts against the video. The script compensates
automatically:

| Source | Delay, samples | Where the figure comes from |
|---|---|---|
| fdkaac | 2048 | measured with a click |
| ffmpeg aac | 1024 | measured with a click |
| libtwolame / ffmpeg mp2 | 482 | the Layer II filterbank |
| ffmpeg ac3 | 256 | measured with a click |
| ffmpeg dca (DTS) | 518 | measured with a click |
| ready-made `.mp2` | 482 | fixed by the format, the same for every encoder |
| ready-made `.aac` | 2048 | an assumption: fdkaac, Apple and Nero use it |

For a ready-made AAC the encoder is unknown and the script says so. If the
file came from ffmpeg's built-in encoder, correct it by hand:

```bash
--audio-aac track.aac --audio-delay-samples 1024
```

To shift a whole track use `--audio-offset 0,-0.12` (per track, in seconds).

### 7.11. How far ahead the audio is handed out

`--audio-lead` (0.16 s by default) says how far ahead of its own PTS an audio
PES goes out, matching the reference capture. The point is the receiver's
elementary stream buffer: hand the audio out too early and the buffer
overflows, which shows up as an occasional loud click rather than as silence.

The multiplexer interpolates time between PCRs to spread its packets, and
that interpolation is deliberately not allowed to run far past the last PCR.
Measured over five minutes, with a source whose PCR is 66.7 ms apart:

| | PTS minus PCR | spread |
|---|---|---|
| unclamped interpolation | +0.137 .. +0.311 s | 174 ms |
| clamped to a quarter of the PCR interval | +0.103 .. +0.198 s | 95 ms |
| the off-air reference | +0.129 .. +0.181 s | 52 ms |

If a deck still produces clicks on an AAC track, try a smaller lead, say
`--audio-lead 0.10`: it gives the buffer more headroom at the cost of less
margin against late delivery.

---

## 8. Service information

### 8.1. Four modes

```bash
--si partial      # default: PAT, PMT, SIT, DIT -- for recording onto D-VHS
--si broadcast    # like on air: PAT, PMT, NIT, SDT, EIT, TOT, BIT
--si deck         # exactly what an HM-DH30000 writes when it re-encodes
--si both         # both sets
--si keep         # touch nothing, only add captions and audio
```

`--no-partial-ts` is the same as `--si keep` (a leftover from early versions).

**`partial`** is what a tuner sends over i.LINK. The surplus tables (NIT,
SDT, EIT, TOT, BIT, SDTT, ECM, null packets) are dropped and a SIT describing
the recording goes out once a second instead. This is the right mode for tape.

**`broadcast`** makes the file look like an off-air recording to players,
MediaInfo and EPG readers. It is redundant for tape but handy for an archive.

### 8.1.1. The decks' own layouts: --deck-profile

`--si deck` reproduces the partial TS a deck writes when it re-encodes a
recording itself. The catch is that decks disagree: LS3 recordings from three
of them differ in nearly every field, so the mode takes a profile.

```bash
--si deck --deck-profile victor-dh30000   # default
--si deck --deck-profile victor-dhx1
--si deck --deck-profile hitachi
```

| | Victor HM-DH30000 | Victor HM-DHX1 | Hitachi DT-DR20000 |
|---|---|---|---|
| PAT programme / PMT PID | 1 / 0x006E | 1 / 0x006E | 100 / 0x1050 |
| PCR | inside the video | own PID 0x0FFF | own PID 0x1010 |
| PCR interval | 16-17 ms | 49.9 ms | 38-39.5 ms |
| Video / audio PID | 0x1000 / 0x1001 | 0x1000 / 0x1002 | 0x1020 / 0x1040 |
| registration MTRM | version 0x10 | version 0x10 | **version 0x07, country JPN** |
| Other PMT descriptors | maximum_bitrate, DTCP | maximum_bitrate, DTCP | DTCP, maximum_bitrate, ARIB 0xC1 |
| SIT | 56 bytes, components and captions, running 4 | 44 bytes, components with language `und`, running 0 | 28 bytes, empty service loop, running 0 |
| SIT repetition | with every PAT | with every PAT | about once a second |
| DIT | yes | no | yes |
| LS3 video | 544x480 16:9 | 544x480 4:3 | 720x480 4:3 |
| LS3 audio | MP2 256 kbit/s | MP2 256 kbit/s | MP2 384 kbit/s |

Each profile copies its deck field for field; against the samples, the PAT,
the PCR PID and every PMT descriptor match byte for byte, and the SIT comes out
at the deck's exact size.

**The most likely reasons a Hitachi refuses a Victor-shaped stream** are the
two that stand out in that table. The MTRM descriptor on the Hitachi is an
older layout -- version 0x07 followed by a country code -- where both Victor
decks and the standard use version 0x10; firmware that checks the version
would reject anything else. And both the Hitachi and the DHX1 carry the PCR
on a PID of its own, in packets with no payload, while the HM-DH30000 keeps it
inside the video.

**A dedicated PCR PID** is built like this. The PCR is lifted out of the video
packets, whose adaptation field keeps everything else, and sent as a payload-
free packet on the new PID at the deck's own interval. On a constant-rate
source the value is computed from the packet's position in the output, over a
long baseline, so it is exact: the samples measure within 0.1 us of a straight
line, the same as the decks themselves. If no free slot turns up in time, the
PCR is inserted anyway and the next free slot is left out to pay for it.

**Every free slot is filled.** On a constant-rate source every place the
source had a null packet -- or its own PAT and PMT, which are replaced -- is
filled with one of our packets or a null, one for one. That keeps the output
exactly at the encoder's rate, the peak equal to the average, and the PCR
positions untouched.

On the HM-DH30000 recording in particular:

* the deck **kept both caption languages** through the re-encode, caption 1
  and caption 2, with the management packet declaring two;
* it **transcoded the audio to MPEG-1 Layer II** -- the broadcast AAC did not
  survive LS3;
* copy control travelled **only in the DTCP descriptor**, with no ARIB
  0xC1/0xDE anywhere -- exactly as the standard says it should for D-VHS. The
  Hitachi is the exception: it carries ARIB 0xC1 next to DTCP.

The Hitachi recording also carries a private stream on PID 0x1030
(data_component_id 0x0001) whose payload looks like line-21 closed-caption
data from its analogue input. The profile does not reproduce it.

`tsinfo.py` shows the MTRM version and country and whether the PCR sits on
its own PID, so a stream can be checked against a deck before recording.

### 8.2. What goes into the tables

With `--si broadcast` the script builds, modelled on the broadcast tables:

| Table | Period | Contents |
|---|---|---|
| NIT | 10 s | network name, service list, satellite parameters |
| SDT | 3 s | service and provider names |
| EIT p/f | 3 s | the current event: title, genre, components |
| EIT schedule | 10 s | a basic schedule (one event, your recording) |
| TOT | 5 s | the time in JST |
| BIT | 10 s | the broadcaster and the table repetition periods |

The video and audio descriptors are derived from the ES themselves:
resolution, scan, aspect ratio, channel count and sample rate.

### 8.3. The genre is read from two different tables

`--genre` writes the value from the ARIB STD-B10 table. Players, MediaInfo
and other tools that grew out of DVB take the names from their own table
(EN 300 468), where the same numbers mean something else entirely:

| `--genre` | Number | Name in ARIB | What DVB tools call it |
|---|---|---|---|
| `news` | 0 | news | undefined |
| `sports` | 1 | sports | Movie/Drama |
| `info` | 2 | information | News/Current affairs |
| `drama` | 3 | drama | Show/Game show |
| `music` | 4 | music | Sports |
| `variety` | 5 | variety | Children's/Youth |
| `movie` | 6 | movie | Music/Ballet/Dance |
| `anime` | 7 | anime | Arts/Culture |
| `documentary` | 8 | documentary | Social/Political/Economics |
| `theatre` | 9 | theatre | Education/Science/Factual |
| `hobby` | A | hobby | Leisure hobbies |
| `welfare` | B | welfare | Special characteristics |

So `--genre movie` showing up in MediaInfo as "music/ballet/dance" is not a
mistake: the value in the file is right, only the caption comes from a
foreign table. A Japanese deck reads it as "movie". The two tables cannot be
satisfied at once, there is only one value in the descriptor. The script
prints both readings so this does not confuse anyone.

The table was checked against the off-air capture: the anime channel carries
7 in its EIT.

### 8.4. Description length

A single descriptor in a TS is at most 255 bytes, so about 230 characters of
description fit into short_event. Anything longer moves into a chain of
extended_event descriptors (0x4E), the way broadcasters do it: up to 16
parts, which the receiver joins back together. If even that is not enough the
tail is dropped with a warning, because an EIT section cannot exceed 4096
bytes.

### 8.5. Where the names come from

For a stream that did not come from Japanese broadcast, everything is set by
options:

```bash
--service-name "BS Test"        # service name
--provider-name "Test Network"  # provider
--event-name "Episode 1"        # event title
--event-text "Description"      # description of any length
--genre anime                   # genre
--jst "2026-08-02 07:00:00"     # recording time
--out-service-id 171            # service_id
--ts-id 0x4012                  # transport_stream_id
--network-id 4                  # network (4 = BS)
```

Strings are encoded into ARIB, so Japanese, Latin and Cyrillic names work
alike. Without `--jst` the time is taken from the file date.

A Japanese stream that already has the tables is left alone by default: the
script says so and keeps the source SI. To rebuild it anyway, use
`--si-regenerate`.

### 8.6. Broadcast PID numbering

```bash
--arib-pids
```

Renumbers the PIDs the broadcast way: PMT 0x01F0, video 0x0100, audio 0x0110
and up, a separate PCR on 0x01FF.

### 8.7. What the script does not do

It never generates ECM or EMM (conditional access), SDTT (receiver firmware
updates), CDT (logos) or BML data carousels. The first would make the stream
formally scrambled; the rest have nothing to do with your recording.

---

## 8.8. D-Theater tape mode

Commercial tapes are laid out differently from an off-air recording. Read off
a demo tape and checked against the standard:

| | broadcast partial TS | D-Theater tape |
|---|---|---|
| Tables | PAT, PMT, SIT, DIT | PAT and PMT only |
| Rate | variable, nulls stripped | constant, padded with nulls (8.9 % on the tape) |
| PAT/PMT | about 10 times a second | about 20 times a second |
| PIDs | PMT 0x01F0, video 0x0100 | PMT 0x0010, video 0x0011, audio 0x0014 |
| Copy control | ARIB 0xC1 and 0xDE | DTCP_descriptor (0x88) |
| Mandatory descriptors | — | registration MTRM, maximum_bitrate, smoothing_buffer |
| Audio | AAC | MPEG-1 Layer II, AC-3, sometimes DTS |
| Captions | ARIB STD-B24 in a separate ES | closed captions inside the video |

```bash
python3 arib_caption_mux.py my.m2t -o tape.m2t --dtheater \
    --audio-mp2 stereo.wav --audio-ac3 surround.wav \
    --dtheater-rate 25 --dtcp-cci never
```

The standard says plainly that copy control in D-VHS travels in the
DTCP_descriptor rather than the ARIB descriptors, and that equipment must not
alter it. So `--copy` is not used in this mode; instead there are
`--dtcp-cci` (free, no-more, once, never), `--dtcp-aps`,
`--dtcp-epn-asserted` and `--dtcp-no-image-constraint`.

The rate is set by `--dtheater-rate`; by default it is the measured peak of
the source plus headroom. If the actual peak turns out higher than declared,
the script warns. Our PCR-to-position accuracy is about ±0.6 ms against
±0.05 ms on a factory tape — it should not affect playback, but the
difference is there.

### What this mode does not do: encrypting the tape itself

Factory D-Theater tapes are encrypted, and that cannot be reproduced — not by
descriptors, not by anything else available from inside the transport stream.
The reason is that the encryption does not live in the stream.

**It is declared in the tape data header.** There is an application-detail
field there: 0000 means a plain MPEG-2 TS, 0001 a CTP stream, and 1xxx an
encrypted MPEG-2 TS, with the three `xxx` bits carrying the lower part of the
region code and the upper part sitting in the neighbouring field. That field
is written by the deck as it records, and there is no reach from the
transport stream down to it: it belongs to a layer below the TS. You may
rewrite the PMT any way you like and application detail will not change.

**It is out of reach at the deck level too.** The standard requires a deck
that is not designed for such data not to output a playback signal at all.
That is why the equipment splits into machines that can decrypt and machines
that cannot: a Mitsubishi HS-HD2000U will not play such cassettes, and
neither will a Victor HM-DH30000, which has no D-Theater support at all.
Which models do support it is a property of the individual machine, so check
yours rather than assuming. But **no consumer deck can encrypt**: the tapes were
duplicated on licensed equipment, the algorithm was never published and the
keys were handed out under licence.

**What is available instead is output protection, not tape protection:**

```bash
python3 arib_caption_mux.py my.m2t -o tape.m2t --dtheater --dtcp-cci never
```

On playback the deck itself becomes a DTCP source and hands the stream out
over i.LINK encrypted — the very behaviour you see with the "copy one
generation" flag. That is the protection mechanism that actually works in
D-VHS; tape encryption stayed with the factory duplication runs.

So `--dtheater` plus `--dtcp-cci never` gives everything that can be had: the
stream structure, the descriptors and the behaviour on the output all match a
tape, and only the fact of tape encryption differs.

---

## 9. Copy-control flags

### 9.1. Reading them

`--list` shows the values (see 3.1).

### 9.2. Writing them

```bash
--copy free           # copy free
--copy once           # copy one generation
--copy never          # copy never
--copy broadcaster    # defined by the broadcaster
--content-availability 0xEF   # the whole 0xDE descriptor byte
```

`digital_recording_control_data` alone is not enough. The low four bits of
the same descriptor are called `user_defined` in the standard, but the ARIB
operational rules give them meaning:

| Bits | Field | Values |
|---|---|---|
| 3-2 | `copy_control_type` | 01 = output encrypted with DTCP, 11 = no encryption, 00 and 10 undefined |
| 1-0 | `APS_control_data` | analogue output protection, 00 = unrestricted |

**A `copy_control_type` of 00 is undefined and the receiver treats it as the
strictest mode.** That is why "copy free" with a zero nibble behaves like
"copy never".

The script fills in the right value itself: 11 (no encryption) for
`--copy free` and 01 (through DTCP) for the other modes, the way broadcast
does. That gives 0x0C for free and 0x84 for copy-one-generation — the latter
matching the off-air capture byte for byte.

To override by hand:

```bash
--copy-control-type protected   # output through DTCP even with copy free
--aps 0                         # analogue output protection bits
--user-defined 4                # the whole nibble at once
```

### 9.3. Copy free but with protected output (EPN)

A `copy_control_type` of 01 is not enough by itself: output protection is
switched on by the `encryption_mode` = 0 bit in descriptor 0xDE, and without
it the receiver hands the stream out in the clear. Verified on a Victor
HM-DHX1: with `--copy free --copy-control-type protected` the recording
plays, but goes out over i.LINK unencrypted.

```bash
--epn     # = --copy free + copy_control_type 01 + 0xDE with encryption_mode 0
```

That gives 0xC1 = 0x04 and 0xDE = 0xEE. If you declare protection only in
0xC1, the script warns.

The values go into the PMT, and when SI is generated also into the EIT and
SIT. Untouched bits are preserved.

### 9.4. Editing only the flags

If only these options are given — no subtitles, no audio, no table changes,
with `--si keep` — the script takes a separate path: it patches the PMT
sections inside the packet, recomputes the CRC and copies the whole rest of
the file **byte for byte**, including the header before the sync byte and a
short tail.

```bash
python3 arib_caption_mux.py sample.m2t -o free.m2t --si keep --copy free
```

```
Copy-control edit, PMT PID 0x01F0: 578 sections, 578 bits changed
Every other byte of the file was copied unchanged.
```

To compare two files byte by byte:

```bash
python3 arib_caption_mux.py a.m2t --diff b.m2t
```

### 9.5. How the flag reaches the tape

The D-VHS standard describes its own CGMS field in the tape data header,
separate from the ARIB descriptor inside the stream. The values are the same:
free, one generation, never. The details: the pair of bits is written to tape
inverted, the value must be the same within a track, and when several
programmes are recorded the strictest one wins.

So there are four layers, and they should not be confused:

| Layer | Where it lives | Who writes it | Do we control it |
|---|---|---|---|
| Descriptors in the stream | PMT, EIT, SIT (0xC1, 0xDE, 0x88) | we do | yes |
| CGMS in the tape header | the tape data header | the deck | no |
| DTCP encryption on the bus | i.LINK | the sending device | indirectly, through the flags |
| Encryption of the tape itself | the application-detail field | licensed duplication equipment | no (see 8.8) |

### 9.6. What these flags really mean

It is easy to overrate them. The real protection on i.LINK is DTCP
encryption, and the mode on the bus is set by the sending device. The bits in
the stream are signalling.

The practical consequence, confirmed on a Victor HM-DH30000: the deck happily
**records** a stream flagged copy-one-generation, but on **playback** it
becomes a DTCP source itself, reads the flag out of the recorded stream and
turns on encryption at the output.

Hence:

- **`--copy free`** if you want to pull the material back off the tape into a
  computer later;
- **`--copy once`** if you are reproducing the behaviour of a real off-air
  recording.

On an off-air recording these flags reflect the broadcaster's terms.

---

## 10. Timing

### 10.1. The zero point

Zero in a subtitle file corresponds to the **earliest audio or video PTS** —
the same convention ffmpeg, mpv and VLC use. A global shift is set with
`--offset`.

### 10.2. Lead time

A caption PES goes out ahead of its own PTS so the receiver has time to
prepare the screen. The default is 0.8 s, as in the off-air capture. Adjust
it with `--lead`.

The caption_management_data packet repeats every 0.5 s (`--mgmt-interval`)
and the SIT every second (`--sit-interval`; ARIB allows no more than 3).

### 10.3. Discontinuities

If the PCR jumps in the source file (a splice), the script inserts a DIT
there and repeats the PAT, PMT and SIT. Caption timing then follows a
continuous playback scale rather than the raw PCR values.

---

## 11. Bit rate and D-VHS modes

When it finishes the script prints the bit rate per PID and a verdict:

```
Duration 57.8 s, average output bit rate 14.25 Mbit/s
   PID 0x0100:   11.335 Mbit/s
   PID 0x0140:    2.479 Mbit/s
D-VHS: fits recording mode HS
```

The modes run the tape at 1/k of the STD speed (Table 17 of the standard).
Mind the difference between the two sets of numbers: the familiar 28.2 / 14.1 /
4.7 Mbit/s are gross channel rates that include the error-correction codes, and
a stream may only occupy 87.9 % of that. The decks confirm it -- an HM-DH30000
writes exactly 12.3956 Mbit/s in STD and 4.1316 in LS3. Aim at the gross figure
and the deck refuses the recording; an HM-DHS1 reports ERROR 108.

| Mode | Payload ceiling | Mode | Payload ceiling |
|---|---|---|---|
| HS | 24.79 Mbit/s | LS3 | 4.13 Mbit/s |
| STD | 12.40 Mbit/s | LS5 | 2.48 Mbit/s |
| LS2 | 6.20 Mbit/s | LS7 | 1.77 Mbit/s |

**What counts is the peak, not the average.** This is the usual trap with the
slow modes: a stream averaging 3.7 Mbit/s looks comfortably inside LS3 and
still plays with artefacts, because it peaks at 6.1. For comparison, an
HM-DH30000 re-encoding into LS3 itself holds a constant 4.1 Mbit/s with 7 %
null padding and never approaches the ceiling.

The safest recipe for a slow mode is a constant-rate source. Encode the video
at a constant rate into a constant-rate container -- the way both decks do --
and this tool will put the audio and the tables into the padding rather than on
top of it:

```bash
python3 arib_caption_mux.py video.m2t subs.srt -o out.m2t \
    --si deck --audio-mp2 dub.wav
python3 tsinfo.py out.m2t --max-mb 64      # confirm the peak before recording
```

Producing that video is a job for your encoder of choice; what matters is that
its transport stream is already constant-rate and padded with null packets.

### 11.1. The peak matters more than the average

A tape records at a fixed rate, and the deck cannot smooth out a spike that
lasts tens of milliseconds: its buffer overflows and playback stalls at that
point. So the script measures the rate between adjacent PCRs and warns:

```
Peak instantaneous rate (between adjacent PCRs): 32.6 Mbit/s at 7.5 s
WARNING: a peak of 32.6 Mbit/s is above the HS limit -- the deck may stall
```

The spike usually comes from the video itself: re-encode it with a lower
`-maxrate`. The script spreads its own packets (audio, captions, tables)
across the stream and never gathers them into bursts.

If the target is an HM-DH30000 this rarely matters: that deck records only in
HS and re-encodes the stream itself when asked for STD or LS3, and the
captions come through the re-encode intact. On decks that record STD directly
the limit is real.

If the stream does not fit STD, `--drop-data` helps: it discards the DSM-CC
data streams (BML carousels), which take a noticeable share of an off-air
recording and have nothing to do with watching it.

---

## 11.2. What the video itself has to satisfy

The deck encodes nothing: it records the transport stream it is handed. So the
video has to meet annex A.2.7 of the standard before it ever reaches this tool:

* MP@ML, or MP@HL / MP@H14L for high definition;
* frame rate 24/1.001, 24, 25, 30/1.001 or 30 Hz (50 and 60/1.001 for HD);
* aspect ratio 4:3 or 16:9;
* a luminance resolution from the tables -- 1920x1080, 1440x1080, 1280x720 or
  720x480 for HD, and 720/704/640/544/480/352 x 480 (352x240) for SD;
* a GOP structure with the sequence header immediately followed by an
  I-picture and repeated at least every 36 display fields on 525/60 systems
  (30 fields on 625/50), that is every 18 or 15 frames.

Both reference streams -- an off-air BS capture and a D-Theater demo tape --
use MP@HL, 4:2:0, interlaced, with a sequence header on every GOP: 17.3 frames
per GOP on air and 12.2 on the tape. Film is stored as progressive frames
inside an interlaced sequence (progressive_frame = 1), not by weaving pairs of
frames together.

What the decks produce themselves, for reference:

| Mode | Raster | Rate | Level |
|---|---|---|---|
| STD | 720x480 | 12.40 Mbit/s constant | MP@ML |
| LS3 | 544x480 | 4.13 Mbit/s constant | MP@ML |

In both cases the peak equals the average, PCR are stamped every 16-17 ms, and
the stream is padded with null packets.


## 12. Ready-made recipes

### 12.1. Your own file for a Japanese deck, as close to broadcast as possible

```bash
python3 arib_caption_mux.py my.m2t episode.ass -o out.m2t \
    --ass-dialogue-only --cyrillic half --drcs-font auto \
    --audio jp.wav --audio-bitrate 256 \
    --si broadcast --arib-pids \
    --out-service-id 171 --ts-id 0x4012 --network-id 4 \
    --service-name "BS Test" --event-name "Episode 1" --genre anime \
    --caption-lang jpn --jst "2026-08-02 07:00:00" \
    --copy free
```

### 12.2. Compatibility with decks from different makers

```bash
python3 arib_caption_mux.py my.m2t subs.srt -o out.m2t \
    --audio jp.wav --audio-mp2 jp.wav --audio-lang jpn,jpn
```

### 12.3. Two subtitle tracks and two audio tracks

```bash
python3 arib_caption_mux.py my.m2t en.ass jp.srt -o out.m2t \
    --caption-lang eng,jpn --cyrillic half \
    --audio jp.wav --audio en.wav \
    --audio-lang jpn,eng --audio-name "Japanese" --audio-name "English"
```

### 12.4. An off-air recording: only replace the captions

```bash
python3 arib_caption_mux.py sample.m2t en.srt -o out.m2t --caption-lang jpn
```

### 12.5. Remux only, no new captions

```bash
python3 arib_caption_mux.py sample.m2t -o out.m2t
```

### 12.6. Only change a copy-control flag

```bash
python3 arib_caption_mux.py sample.m2t -o free.m2t --si keep --copy free
```

### 12.7. A D-Theater style tape

```bash
python3 arib_caption_mux.py my.m2t -o tape.m2t --dtheater \
    --audio-mp2 stereo.wav --audio-ac3 surround.wav \
    --dtheater-rate 25 --dtcp-cci never
```

---

## 13. Checking the result

### 13.1. With libaribcaption

`capcheck.cpp` ships alongside: it decodes the captions out of a finished
file with the very library players use and, if you want, draws every cue into
a PNG.

```bash
git clone https://github.com/xqq/libaribcaption && cd libaribcaption
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
L=$PWD; g++ -O2 -std=c++17 -I$L/include -I$L/build/include -I$L/src \
  -I$L/test/png_writer/include capcheck.cpp $L/test/png_writer/png_writer.cpp \
  $L/build/libaribcaption.a -lfreetype -lfontconfig -lpng -o capcheck

./capcheck out.m2t 0x130          # text, timing, coordinates, colours
./capcheck out.m2t 0x130 pngdir   # plus pictures
./capcheck out.m2t 0x130 lang:2   # the second caption language
```

### 13.2. With tsinfo.py

`tsinfo.py` takes a finished stream apart: tables, descriptors, captions by
language, audio formats checked against IEC 60774-5, and a separate section
on fitness for D-VHS — the peak instantaneous rate with the headroom to the
HS and STD limits, long packet bursts, the PCR interval and the signs of a
partial TS.

```bash
python3 tsinfo.py out.m2t --max-mb 64
python3 tsinfo.py out.m2t --json > report.json
```

### 13.3. With standard tools

```bash
ffprobe -show_programs out.m2t                  # programmes, ES, codecs
ffmpeg -v error -i out.m2t -map 0:a -f null -   # audio check
mediainfo out.m2t                               # how players see the file
```

### 13.4. On the deck itself

The easiest way is to compare step by step, changing one thing at a time:

1. the original off-air file as it is;
2. `arib_caption_mux.py sample.m2t -o t2.m2t` — a remux with no new captions;
3. `arib_caption_mux.py sample.m2t example_ja.srt -o t3.m2t` — your own
   Japanese captions;
4. your own file in full.

Wherever the picture breaks is the cause.

---

### 13.5. A test kit for the deck

`dvhs_test_caption1.ass` and `dvhs_test_caption2.srt` exercise, one by one,
everything this tool can put into a caption stream. Each test is labelled in
small type at the top of the screen, so you always know what you are looking
at. `reference_caption1.png` and `reference_caption2.png` show how every screen
should look, rendered by libaribcaption -- compare the deck against them.

```bash
python3 arib_caption_mux.py video.m2t dvhs_test_caption1.ass dvhs_test_caption2.srt \
    -o test.m2t --caption-lang jpn,jpn
# the same with glyphs outside the ARIB sets drawn as bitmaps:
python3 arib_caption_mux.py video.m2t dvhs_test_caption1.ass dvhs_test_caption2.srt \
    -o test_drcs.m2t --caption-lang jpn,jpn --drcs-font auto
```

Any video of about two and a half minutes will do. The two files are two
languages of one caption ES, so the caption button switches between them;
caption 2 carries a marker every four seconds, so you can tell at any moment
which track is on screen.

**Caption 1 (ASS): layout, sizes, text.**

| Test | What it checks | What you should see |
|---|---|---|
| T01-T03 | one, two, three rows | stacked from the bottom, centred |
| T04 | eight rows | the whole area filled, nothing cut off |
| T05 | 15 full-width glyphs | one row, no wrap |
| T06 | 31 half-width glyphs | one row, no wrap |
| T07 | wrapping at spaces | three balanced rows, no word split |
| T08 | Japanese kinsoku | no `、` or `。` at the start of a row |
| T09 | the 3x3 alignment grid | nine labels at the corners, edges and centre |
| T10 | absolute positions | four labels in the corners of the area |
| T11 | normal and small size | a small row next to a normal one |
| T12 | top and bottom at once | two speakers on one screen |
| T13 | colours in ASS | six colours; blue shows as cyan and black as white |
| T14-T15 | kana, kanji, full- and half-width Latin | all glyphs present |
| T16-T17 | Cyrillic and Greek | 15 letters per row, no gaps |
| T18 | ARIB extra symbols | every symbol drawn, none as the geta mark |
| T19 | glyphs outside the sets | bitmaps with `--drcs-font`, substitutes and geta marks without |
| T20 | eight cues half a second apart | every one of them, none skipped |
| T21 | cues back to back | each replaces the previous without a flash |
| T22 | a three-second gap | a clean empty screen, then the next cue |
| T23 | a twelve-second cue | stable, no flicker or redraw |

**Caption 2 (SRT): colours and switching.** All eight ARIB colours one after
another, including black and blue, which caption 1 cannot show; then the top
and bottom of the screen, a row mixing four colours, and markers until the end.
Black and blue are nearly invisible on the dark box -- that is expected, and it
is the reason the ASS reader remaps them.

**What the kit does not cover.** ARIB STD-B24 can do more than this tool
emits, so those features cannot be tested with it: flashing (FLC), highlight
and underline (HLC), inverted polarity (POL), roll-up and scrolling (SCR),
the built-in sounds (PRA), vertical writing, outlined characters (ORN),
concealment (CDC), character repetition (RPC), and the colour palettes beyond
the eight base colours of palette 0, including half-tone and transparent
colours. A deck that renders everything in the kit correctly handles the
whole of what this tool can produce, not the whole of the standard.

`make_caption_test.py` regenerates both files; edit its test plan to add or
change tests.

## 14. Troubleshooting

| What you see | Most likely |
|---|---|
| Captions drifted, the tail of a row is at the top of the screen | `--positioning acps` was used, `aps` (the default) is needed |
| Captions show on the SD output but not on HD | a limitation of the deck; check with the ladder in 13.4 |
| No captions at all | only the HM-DH30000 renders them; the others record but do not display them |
| A Hitachi deck does not accept the stream | `--si deck --deck-profile hitachi`, see 8.1.1 |
| A geta mark instead of a glyph | the glyph is not in JIS X 0208 -> `--drcs-font auto` |
| Rows are too short | `--cyrillic half`, a wider `--area` |
| Control codes instead of text | `--caption-lang eng` without `--encoding utf8`, see 4.4 |
| A blank screen in `utf8` mode | the deck does not support UCS, go back to `jis` |
| Small ASS text seems to have vanished during a check | that is `--ass-small ssz`, see 6.4 |
| The audio drifted by 20-40 ms | a ready-made `.aac` from ffmpeg -> `--audio-delay-samples 1024` |
| A Japanese deck is silent | the audio is not AAC -> `--audio file.wav` |
| An occasional loud click on an AAC track | the audio is handed out too early, see 7.11; try `--audio-lead 0.10` |
| Another maker's deck is silent | an `--audio-mp2` track is needed |
| PCM sounds like noise in a player | the player expects ffmpeg's order, see 7.8 |
| Does not fit STD | `--drop-data`, a lower audio bit rate |
| Artefacts in a slow mode (LS3 and below) | the peak is above the mode ceiling, see 11 |
| Artefacts in STD | same cause: the deck's own STD is a constant 12.4 Mbit/s, measure your peak |
| "the file does not look like a ... stream" | the wrong format was passed (mp3 instead of mp2, say) |
| "the event description does not fit" | a description longer than about 4 KB, the tail was dropped |
| The deck stalls at the same places | a rate spike, see 11.1 |
| You want to encrypt the tape itself | impossible, see 8.8; only output protection is available |
| Only the first subtitle track shows | `--caption-multi es` was used, `lang` is needed |
| Playback from tape goes out encrypted | the flag is not `free`, see 9.6 |
| `--copy free` behaves like `copy never` | an old version wrote `copy_control_type` = 00, see 9.2 |
| ASS signs overlap the dialogue | `--ass-signs top` or `--ass-dialogue-only` |

The script writes its warnings to the error stream, so they stay visible even
when the output is redirected to a file.

---

## 15. Every option

The full list is always available with:

```bash
python3 arib_caption_mux.py --help
```

### Basics

| Option | Default | Meaning |
|---|---|---|
| `input` | — | input MPEG-TS |
| `subs ...` | — | one or more SRT/ASS files |
| `-o` | — | output file |
| `--list` | — | show the contents and exit |
| `--service-id` | the first with video | which service to take |
| `--diff FILE` | — | byte comparison |

### Subtitles

| Option | Default | Meaning |
|---|---|---|
| `--caption-lang` | `jpn` | track languages (eng/tgl/por/spa change the encoding scheme, see 4.4) |
| `--encoding` | `jis` | ARIB sets or UCS/UTF-8 |
| `--caption-pid` | 0x130, 0x131... | track PIDs |
| `--caption-multi` | `lang` | languages in one ES or separate ES |
| `--offset` | 0 | offset, seconds |
| `--existing` | `replace` | whether to replace broadcast captions |
| `--positioning` | `aps` | how rows are positioned |
| `--cyrillic` | `full` | Cyrillic width |
| `--drcs-font` | — | font for glyphs outside the sets |
| `--area` | 620x480+170+30 | caption area inside the 960x540 plane |
| `--lead` | 0.8 | PES lead time, seconds |
| `--mgmt-interval` | 0.5 | management packet period, seconds |

### ASS

| Option | Default | Meaning |
|---|---|---|
| `--ass-dialogue-only` | off | dialogue only |
| `--ass-list-styles` | — | print the verdict per style |
| `--ass-signs` | `place` | what to do with signs |
| `--ass-only-styles` / `--ass-skip-styles` | — | manual style selection |
| `--ass-small` | `ssz` | size of small text |
| `--ass-min-duration` | 0.3 | short-screen threshold, seconds |

### Audio

| Option | Default | Meaning |
|---|---|---|
| `--audio` / `--audio-wav` / `--audio-aac` / `--audio-mp2` / `--audio-ac3` / `--audio-dts` / `--audio-pcm` | — | tracks |
| `--pcm-bit-order` | `dvhs` | bit order in the SMPTE 302M field |
| `--keep-audio` | off | keep the source audio |
| `--audio-lang` | `jpn` | track languages |
| `--audio-name` | — | track names |
| `--audio-channels` | as in the WAV | 1, 2 or 6 |
| `--audio-bitrate` | 256 / 384 / 144 | kbit/s |
| `--audio-offset` | 0 | offset, seconds |
| `--audio-delay-samples` | measured | encoder delay |
| `--aac-encoder` | `auto` | fdkaac or ffmpeg |
| `--mp2-encoder` | `auto` | libtwolame or ffmpeg |
| `--audio-lang-pmt` | off | language in the PMT for players |

### Tables and flags

| Option | Default | Meaning |
|---|---|---|
| `--dtheater` | off | D-Theater tape layout (see 8.8) |
| `--dtheater-rate` | the peak | tape rate, Mbit/s |
| `--dtcp-cci` | `never` | copy control on the tape |
| `--dtcp-aps` / `--dtcp-epn-asserted` / `--dtcp-no-image-constraint` | — | the other DTCP fields |
| `--psi-interval` | 0.047 | PAT/PMT period in tape mode, seconds |
| `--smoothing-buffer` | 950272 | buffer size in the smoothing_buffer_descriptor |
| `--ffmpeg` | `ffmpeg` | path to ffmpeg |
| `--si` | `partial` | which tables to emit (`partial`, `broadcast`, `deck`, `both`, `keep`) |
| `--deck-profile` | `victor-dh30000` | whose layout `--si deck` reproduces: `victor-dh30000`, `victor-dhx1`, `hitachi` |
| `--si-regenerate` | off | rebuild the SI of a Japanese stream |
| `--arib-pids` | off | broadcast PID numbering |
| `--sit-interval` | 1.0 | SIT period, seconds |
| `--network-id` / `--media-type` | from the NIT | network |
| `--service-name` / `--provider-name` | — | names for the SDT |
| `--event-name` / `--event-text` / `--genre` / `--event-id` / `--event-duration` | — | the event for the EIT |
| `--jst` | from the file | recording time |
| `--ts-id` / `--out-service-id` / `--broadcaster-id` / `--network-name` | from the input | identifiers |
| `--copy` / `--content-availability` | from the input | copy-control flags |
| `--copy-control-type` | `auto` | whether to encrypt the output |
| `--epn` | off | copy free with protected output |
| `--aps` / `--user-defined` | from the input | analogue protection, the whole nibble |
| `--keep-ca` | off | do not strip the CA_descriptor |
| `--drop-data` | off | drop DSM-CC |
| `--peak-rate` | measured | peak_rate in the SIT |
| `--no-superimpose` | off | no superimpose stream |
| `--simple-pes` | off | a simplified PES header |
| `--no-partial-ts` | off | a synonym for `--si keep` |


---

## Glossary

Abbreviations used above, in the order a newcomer usually meets them.

### Standards and organisations

| Term | Meaning |
|---|---|
| **ARIB** | Association of Radio Industries and Businesses, the Japanese body whose standards define digital broadcasting there |
| **ARIB STD-B24** | the caption standard: character sets, control codes, screen layout |
| **ARIB STD-B21** | the receiver standard; it defines the partial TS a tuner sends over i.LINK |
| **ARIB STD-B10** | the service-information standard: tables and descriptors |
| **IEC 60774-5** | the D-VHS standard (published in Europe as BS EN 60774-5) |
| **ISDB** | Integrated Services Digital Broadcasting, the Japanese broadcasting system |
| **DVB** | Digital Video Broadcasting, the European system; similar tables, different details |
| **SMPTE 302M** | the standard for carrying linear PCM audio in an MPEG-2 stream |
| **ABNT** | the Brazilian standards body; its Latin character sets appear in the ARIB language rules |

### The transport stream

| Term | Meaning |
|---|---|
| **TS** | Transport Stream, the 188-byte packet format everything here is made of |
| **PID** | Packet Identifier, the 13-bit number that says which stream a packet belongs to |
| **ES** | Elementary Stream, one continuous stream of video, audio or captions |
| **PES** | Packetized Elementary Stream, an ES cut into packets with headers and timestamps |
| **PSI / SI** | Program Specific Information / Service Information: the tables describing the stream |
| **PCR** | Program Clock Reference, the clock samples that tell the receiver how fast to run |
| **PTS / DTS** | Presentation / Decoding Time Stamp: when a frame should be shown or decoded |
| **CC** | continuity_counter, a 4-bit counter per PID used to spot lost packets |
| **CRC** | the checksum that protects a table section or an audio frame |
| **partial TS** | a stripped-down stream carrying one programme, what a tuner hands a recorder |

### The tables

| Table | Meaning |
|---|---|
| **PAT** | Program Association Table: which programmes exist and where their PMT is |
| **PMT** | Program Map Table: which streams make up one programme |
| **SIT** | Selection Information Table: describes what was recorded, used in a partial TS |
| **DIT** | Discontinuity Information Table: marks a splice |
| **NIT** | Network Information Table: the network and its transponders |
| **SDT** | Service Description Table: service and provider names |
| **EIT** | Event Information Table: the programme guide |
| **TOT / TDT** | Time Offset / Time and Date Table: the broadcast clock |
| **BIT** | Broadcaster Information Table: the broadcaster and table repetition periods |
| **CAT / ECM / EMM** | conditional-access tables and messages: the scrambling system |
| **SDTT** | Software Download Trigger Table: receiver firmware updates |
| **CDT** | Common Data Table: channel logos |
| **BML** | Broadcast Markup Language, the data-broadcasting content carried in DSM-CC carousels |
| **DSM-CC** | Digital Storage Media Command and Control, the carousel mechanism that carries BML |
| **EPG** | Electronic Programme Guide, what the EIT feeds |

### Captions

| Term | Meaning |
|---|---|
| **DRCS** | Dynamically Redefinable Character Set: glyphs sent as bitmaps inside the stream |
| **G0 / G1** | the invoked character sets: kanji and alphanumeric |
| **LS0 / LS1** | Locking Shift, the codes that switch between those sets |
| **ESC** | the escape code that designates a set, used here to reach DRCS |
| **NSZ / MSZ / SSZ** | Normal / Middle / Small SiZe: a full cell, half width, or the small ruby size |
| **APS / ACPS** | Active Position Set / Active Coordinate Position Set: cursor placement by cell or by dot |
| **SWF / SDF / SDP** | Set Writing Format / Display Format / Display Position: the plane and the caption area |
| **SSM / SHS / SVS** | character size, horizontal spacing, vertical spacing |
| **CS** | Clear Screen |
| **FLC / HLC / POL / SCR / PRA / ORN / CDC / RPC** | flashing, highlight, polarity, scrolling, built-in sound, ornament, concealment, repetition: caption controls this tool does not emit |
| **TCS** | the field saying whether the text is in the ARIB sets or in UCS |
| **UCS** | Universal Character Set, that is Unicode; the text then travels as UTF-8 |
| **JIS X 0208** | the Japanese character set that also holds Cyrillic and Greek |
| **ruby** | the small annotation text printed above a word; SSZ is meant for it |
| **ASS / SSA** | Advanced SubStation Alpha, the subtitle format with styles and positioning |
| **SRT** | SubRip, the plain subtitle format |

### Audio and video

| Term | Meaning |
|---|---|
| **AAC** | Advanced Audio Coding, what Japanese broadcasting uses |
| **AAC-LC** | its Low Complexity profile, the only one D-VHS allows |
| **ADTS** | Audio Data Transport Stream, the frame format AAC travels in |
| **MP2** | MPEG-1 Audio Layer II |
| **AC-3** | Dolby Digital |
| **DTS** | DTS Coherent Acoustics |
| **PCM / LPCM** | uncompressed audio; here per SMPTE 302M |
| **LFE** | the Low Frequency Effects channel, the ".1" of 5.1 |
| **GOP** | Group Of Pictures, the repeating unit of an MPEG-2 video stream |
| **VBV** | Video Buffering Verifier, the decoder buffer model that limits bursts |
| **MP@ML / MP@HL / MP@H14L** | Main Profile at Main, High or High-1440 Level: the MPEG-2 profile and level |
| **MPEG-1 / MPEG-2** | the coding families; the video here is always MPEG-2, the MP2 audio is MPEG-1 |
| **CBR / VBR** | constant or variable bit rate |

### Recording and protection

| Term | Meaning |
|---|---|
| **D-VHS** | the digital VHS format: the deck records the transport stream as it is |
| **D-Theater** | pre-recorded D-VHS movie tapes, encrypted at the factory |
| **HS / STD / LS2 / LS3 / LS5 / LS7** | the tape speeds, from fastest to slowest; LS*k* runs the tape at 1/*k* of the STD speed |
| **i.LINK** | Sony's name for IEEE 1394 (FireWire), the digital link to the deck |
| **DTCP** | Digital Transmission Content Protection, the encryption used on that link |
| **DTLA** | the licensing body behind DTCP; its CA_System_ID 0x0FFF appears in the descriptor |
| **CGMS** | Copy Generation Management System, the copy flag in the tape data header |
| **EPN** | Encryption Plus Non-assertion: copy freely, but hand the stream out protected |
| **APS** | Analogue Protection System, the anti-copy signal on the analogue output |
| **CCI** | Copy Control Information, the two bits saying free / one generation / never |
| **MTRM** | the registration identifier marking a stream as D-VHS compliant |
| **BSSD** | the registration identifier marking an SMPTE 302M audio track |
| **CTP** | Common Transport Packet, an alternative payload type in the tape header |

### Miscellaneous

| Term | Meaning |
|---|---|
| **BS** | Broadcasting Satellite, the Japanese satellite platform at 110°E |
| **CS** (in *media_type*) | Communication Satellite, the other Japanese satellite platform |
| **JST** | Japan Standard Time, UTC+9, the clock the TOT carries |
| **MJD** | Modified Julian Date, how dates are encoded in the tables |
| **ISO 639-2** | the three-letter language codes: jpn, eng, rus |
| **UTF-8** | the Unicode encoding used when the captions travel in UCS mode |
| **CC** (in *closed captions*) | the American caption system, carried inside the video rather than as a separate ES |

---

## Appendix. What was verified, and how

| Check | How |
|---|---|
| Captions decode | libaribcaption, the whole 7484-glyph set |
| Geometry and wrapping | rendered to PNG and compared with the off-air capture |
| Positioning | Victor HM-DH30000, measured from screenshots |
| Audio sync | a click in the WAV, its position measured in the finished TS |
| 5.1 channel order | a different tone per channel, compared before and after |
| Encoder delays | measured with a click through the full cycle |
| Tables | parsed with separate code, CRC and periods checked |
| Copy-control flags | byte comparison against a reference `copyctl.py` |
| Recording and playback | Victor HM-DH30000, HM-DHX1 |
| The deck's own partial TS | compared against an HM-DH30000 LS3 re-encode |
| Audio formats on hardware | Victor HM-DHX1 and HM-DH30000: AAC, MP2, AC-3 |

Checked against IEC 60774-5 (BS EN 60774-5:2004): the audio requirements,
the CGMS field in the tape header, the D-Theater encryption mechanism (the
application-detail field) and the D-VHS MPEG format (registration MTRM,
DTCP_descriptor, maximum_bitrate, smoothing_buffer).

The structure of `--dtheater` mode was checked against a D-Theater demo tape:
the set and order of descriptors match, the PAT/PMT rate is 21.2 against
20.1 per second, and the stream is constant-rate with null padding.

Not verified: the behaviour of decks from other makers, multichannel AAC on a
real deck, and switching between caption 1 and caption 2 on a deck.
