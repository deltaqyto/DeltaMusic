# Client protocol

Everything needed to write a client. Read [core.md](core.md) for the vocabulary.

Clients send commands and get one response each. Core sends events to every attached client.

The peer commands, their jobs and their events are in [peer-protocol.md](peer-protocol.md).

## Conventions

- Times and durations are seconds, as floats.
- Timestamps are UTC, ISO 8601, millisecond precision.
- Volume runs 0.0 to 1.0.
- Songs, playlists, and playlist entries carry integer ids.
- Songs and playlists carry a `uuid` as well, which travels with them between cores.
- Queue entries carry their own ids, which last only as long as the entry.
- The queue's `source` is nullable. Nothing else in a state snapshot is, apart from `song_id` and `playlist_id` where noted.
- Payloads are JSON.

## Envelopes

```json
{"v": 3, "id": "c-17", "method": "seek_to", "params": {"seconds": 91.5}}

{"v": 3, "id": "c-17", "ok": true, "result": {}}
{"v": 3, "id": "c-17", "ok": false, "error": {"code": "NOT_FOUND", "message": "no entry 5501", "detail": {"entry_id": 5501}}}

{"v": 3, "seq": 8841, "ts": "2026-08-05T11:20:03.512Z", "type": "QueueChanged", "payload": {}}
```

- `v` - protocol version.
- `id` - client-chosen, echoed back.
- `seq` - monotonic per connection.

## Attaching

Call `get_state` on connect. It returns a complete snapshot.

## Features

`get_state` carries `features`, naming what is true of this core. It does not change within a run.

```json
{"features": ["private_library"]}
```

| Name              | Meaning                                  |
|-------------------|------------------------------------------|
| `private_library` | The library folder is private            |

A client ignores a name it does not know.

## Revisions

- `queue_revision` - moves on any edit to the queue, core's own trim and refill included.
- `library_revision` - moves on a write to a song or playlist, or a scan that changed something.

## Session state

Returned by `get_state`, carried by `Heartbeat`.

```json
{
  "playback": {
    "status": "playing",
    "song_id": 812,
    "position": 91.5,
    "rate": 1.0,
    "duration": 252.0,
    "volume": 0.64,
    "repeat": "playlist",
    "shuffle": true,
    "queue_revision": 42
  },
  "queue": {
    "entries": [
      {"entry_id": 61, "song_id": 901, "origin": "user"},
      {"entry_id": 62, "song_id": 640, "origin": "user"},
      {"entry_id": 63, "song_id": 812, "origin": "user"},
      {"entry_id": 64, "song_id": 77, "origin": "user"},
      {"entry_id": 65, "song_id": 155, "origin": "autofill"}
    ],
    "cursor": 2,
    "source": {"kind": "playlist", "playlist_id": 4},
    "queue_revision": 42
  },
  "library_revision": 418
}
```

- `status` - `idle`, `playing`, `paused`. `song_id` is null when idle.
- `repeat` - `none`, `song`, `playlist`.
- `source` - null when the queue has no source, which is the case before the first `play_playlist` or `play_songs` and after `queue_clear`. Check for null before reading into it.
- `source.kind` - `playlist` or `songs`. `playlist_id` is null for `songs`.
- `position` - where playback was when the state was built. `rate` is how fast it advances. Extrapolate between heartbeats.
- `cursor` - index into `entries` of what is playing, or -1 when the queue is empty.
- `origin` - `user` if a client put the entry there, `autofill` if core's refill drew it. Ahead of the cursor every `user` entry precedes every `autofill` one. Behind it every entry is `user`, since the cursor passing an entry adopts it.

The queue carries song ids, not songs. `get_songs` resolves them.

An entry id names a slot in the queue for as long as that slot exists, and only within one run of core. It is not a database row, it is never reused, and it must not be stored.

## Heartbeat

Once per second, carrying `playback`. It also carries `queue` when `queue_revision` has moved since the last one that did, and on every tenth heartbeat.

## Commands

### Transport

| Command          | Params                                 | Result     |
|------------------|----------------------------------------|------------|
| `play`           |                                        | `playback` |
| `pause`          |                                        | `playback` |
| `stop`           |                                        | `playback` |
| `seek_to`        | `seconds`                              | `playback` |
| `seek_by`        | `delta_seconds`                        | `playback` |
| `next_track`     |                                        | `playback` |
| `previous_track` |                                        | `playback` |
| `set_repeat`     | `mode`                                 | `playback` |
| `set_shuffle`    | `enabled`                              | `playback` |
| `set_volume`     | `level`                                | `playback` |
| `play_playlist`  | `playlist_id`, `start_index`, `paused` | `playback` |
| `play_songs`     | `song_ids`, `paused`                   | `playback` |

- `paused` defaults to false. True seeds the queue and opens the song without starting it. The state comes back `paused` at position 0, and the song does not count as played until it is.
- `previous_track` moves back one entry regardless of position.
- `play_playlist` and `play_songs` fail on the song they open: 

  - `TRACK_ABSENT` when its file is not on disk, 
  - `PLAYBACK_FAILED` when the file is there and will not decode. 
  - `TRACK_ABSENT` leaves the session untouched. 
  - `PLAYBACK_FAILED` leaves it idle with an empty queue and no source, since the queue had already been replaced by then.
- Moving through the queue never fails this way. `next_track`, `previous_track` and the end of a song emit `TrackFailed` and carry on to the next entry.
- `seek_to` and `seek_by` clamp to the current song.
- `mode` is `none`, `song` or `playlist`, and defaults to `playlist`.

  - Under `song` the current song repeats. 
  - Under `playlist` the queue refills from its source as it runs short. 
  - Under `none` there is no refill, and playback stops when the queue runs out.
- Shuffle is incompatible with no refill, since there is no defined end. The two are bound: `set_repeat` to `none` sets `shuffle` false, and `set_shuffle` true while `repeat` is `none` sets `repeat` to `playlist`. 
Either command returns the resulting `playback`, so a client reads both values back from its own response to avoid duplicating logic.

### Queue

| Command        | Params                       | Result  |
|----------------|------------------------------|---------|
| `get_queue`    |                              | `queue` |
| `queue_insert` | `song_ids`, `after_entry_id` | `queue` |
| `queue_remove` | `entry_ids`                  | `queue` |
| `queue_move`   | `entry_id`, `after_entry_id` | `queue` |
| `queue_clear`  |                              | `queue` |

- `after_entry_id` names the entry to land behind. Null means the end of the user run for `queue_insert`, and directly after the cursor for `queue_move`.
- Inserted entries are `user`. So is everything between the cursor and the landing place, for either command. Placing a song past the autofill tail adopts what it passed.
- `after_entry_id` must name the current entry or one ahead of it. Aiming into the history is `INVALID_ARGUMENT`.
- `queue_remove` takes any entries, history included. Ids that are already gone are skipped, so removing twice is not an error.
- Removing the cursor's entry moves playback to the next song.
- `queue_clear` leaves the current song and drops the source, so `source` becomes null and the refill stops for good. 
`repeat` still reports `playlist`, but nothing will refill again. Only a fresh `play_playlist` or `play_songs` gives the queue a source again.

### Library

| Command             | Params                                | Result           |
|---------------------|---------------------------------------|------------------|
| `list_songs`        | `query`, `offset`, `limit`            | `{songs, total}` |
| `get_songs`         | `song_ids`                            | `{songs}`        |
| `get_songs_by_uuid` | `uuids`                               | `{songs}`        |
| `update_song`       | `song_id`, `fields`                   | `song`           |
| `forget_song`       | `song_id`                             |                  |
| `list_playlists`    |                                       | `{playlists}`    |
| `get_playlist`      | `playlist_id`                         | `playlist`       |
| `create_playlist`   | `name`, `song_ids`                    | `playlist`       |
| `update_playlist`   | `playlist_id`, `fields`               | `playlist`       |
| `delete_playlist`   | `playlist_id`                         |                  |
| `playlist_add`      | `playlist_id`, `song_ids`, `at_index` | `playlist`       |
| `playlist_remove`   | `entry_ids`                           | `playlist`       |
| `playlist_move`     | `entry_id`, `to_index`                | `playlist`       |

- `get_songs_by_uuid` answers with the `song` shape for each uuid this core holds a row for. A uuid with no row is absent from the answer.
- `update_song` takes `name`, `artist`, `metadata`. The file on disk keeps its name.
- `update_playlist` takes `name`, `metadata`.
- `playlist_remove` and `playlist_move` take entry ids, which arrive with the playlist. Duplicates are allowed.
- `forget_song` drops the record and every playlist entry pointing at it. The file is untouched, except on a core whose library folder is private, which deletes the file with the record.
- `All Tracks` lists and resolves like any playlist, and rejects every write. Its entry ids are synthetic negative integers to avoid conflict.

```json
{
  "song": {
    "id": 812, "uuid": "b81f2c66-...", "name": "Slow Burn Interlude", "artist": "Kestrel Field",
    "duration": 252.0, "file_size": 6291456,
    "location": "2026/03/Slow Burn Interlude - Kestrel Field.opus",
    "found_on_disk": true, "metadata": {},
    "added_at": "2026-03-14T22:01:55.000Z",
    "last_played_at": "2026-08-05T11:18:31.000Z", "play_count": 12
  },
  "playlist": {
    "id": 4, "uuid": "6f3d1b04-...", "name": "Late night", "metadata": {},
    "created_at": "2026-01-02T19:44:00.000Z", "modified_at": "2026-07-30T08:12:04.000Z",
    "entries": [{"entry_id": 5501, "song_id": 812}, {"entry_id": 5502, "song_id": 77}]
  }
}
```

`location` is null on a song no file has ever been placed for.

`list_playlists` returns each playlist without `entries` and with a `song_count`.

## Events

| Type              | Payload                            | Sent when                             |
|-------------------|------------------------------------|---------------------------------------|
| `Heartbeat`       | `playback`, sometimes `queue`      | every second                          |
| `TrackChanged`    | `song_id`, `cursor`                | the cursor lands on a different song  |
| `PlaybackChanged` | `playback`                         | play, pause, seek, stop, mode, volume |
| `QueueChanged`    | `queue_revision`                   | the queue was edited                  |
| `LibraryChanged`  | `library_revision`, `scope`, `ids` | a song or playlist was written        |
| `ScanProgress`    | `scanned`, `total`, `phase`        | during the startup scan               |
| `TrackFailed`     | `song_id`, `message`               | a song could not be played            |

- `scope` - `song`, `playlist` or `statistics`, the last being a play count and a last-played time. `ids` lists what changed.
- `phase` - `walking`, `reconciling`, `inserting`, `done`.
- `QueueChanged` carries no contents, only the revision.
- Events reach the client that caused them too.

## Errors

| Code               | Meaning                                                               |
|--------------------|-----------------------------------------------------------------------|
| `NOT_FOUND`        | No such song, playlist or entry                                       |
| `INVALID_ARGUMENT` | Bad parameter, or a write aimed at `All Tracks`                       |
| `CONFLICT`         | A playlist by that name exists                                        |
| `TRACK_ABSENT`     | The song's file is not on disk                                        |
| `PLAYBACK_FAILED`  | The file is there and would not play                                  |
| `INTERNAL`         | Anything else                                                         |

The peer errors are in [peer-protocol.md](peer-protocol.md).
