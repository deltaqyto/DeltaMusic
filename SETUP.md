# DeltaMusic setup

Windows only.

## 1. Install

```bash
pip install -r requirements.txt
```

## 2. Install VB-CABLE

Install [VB-CABLE](https://vb-audio.com/Cable/), then set your player's
output device to **CABLE Input**.

You play into `CABLE Input` and record from `CABLE Output`.

## 3. Identify the device

A cable appears once per host API, so `CABLE Output` matches several PortAudio devices.

Start audio playing, then:

```bash
python -m acquisition.tools.windows_probe --match CABLE
```

```
  SIGNAL   [22] CABLE Output (VB-Audio Virtual Cable) (Windows WASAPI, 2ch)
           peak  -23.5 dBFS   rms 0.019958
  silence  [3]  Microphone (Realtek(R) Audio) (MME, 2ch)
           peak   -inf dBFS   rms 0.000000
```

`SIGNAL` means audio is arriving, `silence` means the device opened but delivered nothing, `FAILED` means it would not open. 

Pick a host API from the ones showing signal, in this order:

| Host API        | Notes                                                                                  |
|-----------------|----------------------------------------------------------------------------------------|
| **WASAPI**      | Use this.                                                                              |
| **WDM-KS**      | Lowest latency, but needs exclusive access and fails if anything else holds the cable. |
| **DirectSound** | Resamples and adds buffering.                                                          |
| **MME**         | 16-bit, high latency.                                                                  |

Record the device name and host API.

## 4. Configure

`config/acquisition_config.json` is written with defaults on first run. Edit it and re-run. 
Backend settings go in a section named after the backend. Everything else is top level.

```json
{
  "app_id": "DeltaAudioGen.exe",
  "save_directory": "recordings",
  "container": "opus",
  "windows": {
    "device": "CABLE Output (VB-Audio Virtual Cable)",
    "hostapi": "WASAPI",
    "loop_seconds": 2.0
  }
}
```

Top level:

| Setting                        | Meaning                                                                                                |
|--------------------------------|--------------------------------------------------------------------------------------------------------|
| `backend`                      | `null` selects by platform.                                                                            |
| `app_id`                       | The player's `source_app_user_model_id`. Triggering only; audio comes from `windows.device`.           |
| `poll_interval`                | Seconds between session reads. Default `0.1`.                                                          |
| `save_directory`               | Relative paths resolve against the project root.                                                       |
| `filename_template`            | Default `{title} ~~ {artist}`. The ` ~~ ` separator is what the library scanner splits on, so a custom template should keep it. Also `{album}`, `{album_artist}`, `{year}`, `{track_number}`, `{genre}`. |
| `container`                    | See the table below.                                                                                   |
| `subtype`                      | Sample depth. Lossless containers only.                                                                |
| `overwrite`                    | `false` skips a track whose filename already exists.                                                   |
| `dither`                       | Applied when reducing bit depth.                                                                       |
| `start_lead_ms`                | Extra pre-roll beyond the reported position.                                                           |
| `completion_tolerance_seconds` | How close to its duration a track must get to count as played out.                                     |
| `end_tolerance_seconds`        | How far the captured length may differ from the track duration. Default `2.0`.                         |
| `silence_threshold`            | Peak amplitude counting as silence. Default `0.0001`.                                                  |
| `max_silence_fraction`         | Silence share above which a track is rejected. Default `0.7`.                                          |
| `log_level`                    | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.                                                       |

`windows` section:

| Setting                  | Meaning                                                                            |
|--------------------------|------------------------------------------------------------------------------------|
| `device`                 | Case-insensitive substring of the device name, or an index. Ambiguity is an error. |
| `hostapi`                | Substring of the host API name. Disambiguates the `CABLE Output` entries.          |
| `samplerate`, `channels` | `null` adopts the device defaults.                                                 |
| `loop_seconds`           | Pre-roll buffer. Caps how far back a recording can reach. Default `2.0`.           |
| `blocksize`              | Frames per callback. `0` lets PortAudio choose.                                    |
| `latency`                | `"low"`, `"high"`, or seconds.                                                     |
| `max_recording_seconds`  | Runaway guard. Tripping it discards the recording. Default `900`.                  |

## 5. Run

```bash
python -m entry.acquire
```

```bash
python -m entry.acquire --list-devices
```

## Output format

Sizes are per stereo minute at 48 kHz.

| `container`       | Size/min | Notes                                          |
|-------------------|----------|------------------------------------------------|
| `opus`            | ~0.7 MB  | Default. Encodes only at 48/24/16/12/8 kHz.    |
| `ogg`             | ~0.8 MB  | Vorbis. Accepts any samplerate.                |
| `mp3`             | ~1 MB    | For downstream tools that accept nothing else. |
| `flac` + `PCM_16` | ~7 MB    | Lossless.                                      |
| `flac` + `PCM_24` | ~10 MB   | Lossless at capture depth.                     |
| `wav`             | 16 MB    | Uncompressed.                                  |

Opus at a samplerate it does not support is refused at startup, before anything is recorded. 
Either set the cable to 48 kHz, pin `samplerate` in the `windows` section, or use `ogg`.

## Troubleshooting

**Everything records silence.** Wrong device. Re-probe with audio playing.

**`'CABLE Output' is ambiguous, 4 devices match`.** Set `windows.hostapi`.

**`Error opening InputStream ... -9999` on WDM-KS.** Something else holds the pin. Use WASAPI.

**Every track logs "missed the start".** Started mid-track, or `start_lead_ms` exceeds `windows.loop_seconds`. The next track records normally.

**Tracks rejected as silence.** The session is playing but the cable is not carrying audio. Check the player's output device.

**Dropout warnings.** `xruns` counts stream overflows, which are real holes in the audio. Raise `windows.blocksize`, or close whatever is loading the machine.
