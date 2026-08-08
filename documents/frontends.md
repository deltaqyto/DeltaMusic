# frontends

A frontend is a client. It talks to core through `CoreClient` and holds no library or playback state of its own, only what it needs to draw. The bundled one is PyQt6, in `frontends/qt`, and calls `CoreService` in-process.

## Remembered settings

`config/settings.json` holds what the app decided rather than what the operator configured. `config/config.json` is hand-written and read on start; `settings.json` is written by the app as the user works. Both are untracked.

```json
{
  "volume": 0.64,
  "shuffle": true,
  "repeat": "playlist",
  "song_id": 812,
  "playlist_id": 4
}
```

- Missing or unparseable means the defaults. It is never an error.
- Unknown keys are ignored, so an older file still loads.
- Every field is validated on load and falls back on its own. A volume outside 0 to 1 is clamped, a repeat mode that is not one of the three is dropped, and ids must be non-negative integers.
- `repeat` and `shuffle` are validated as a pair and dropped as a pair, since shuffle with no refill is a combination core will not hold.
- `song_id` is the last song that played and `playlist_id` the playlist it came from, null when playback was seeded from a loose list of songs.

Writes are debounced by five seconds, since dragging a slider emits a change per pixel, and flushed on close so quitting inside the window does not lose the setting. 
Only a value that actually changed restarts the clock: heartbeats arrive every second and would otherwise hold the write off forever. 
Volume zero is applied but not saved, because mute is a transient state and coming back to a silent player is worse than forgetting it was muted.

## Restoring a session

On attach the frontend pushes volume, repeat and shuffle, then reopens the last song with `paused` true. Playback never resumes by itself: the app always starts paused at position 0, whatever it was doing when it closed.

The song is restored through its playlist when it is still in one, so the refill has the same source it had before. If the playlist is gone or no longer holds the song, the song is restored on its own through `play_songs`. 
If that fails too, the app just starts empty.

`config.initial_volume` still decides what core plays at before any client connects.

## The queue pane

The pane renders `QueueState` as it arrives. Entries ahead of the cursor split at the origin boundary, `user` entries drawn at full weight and the `autofill` tail dimmed, so what was asked for reads apart from what core guessed. 
Removal sends the selected entry ids. See [client-protocol.md](client-protocol.md) for the queue commands themselves.
