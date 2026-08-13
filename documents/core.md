# core

Core keeps the record of every song on the machine, organises them into playlists, and plays them. Clients connect to it and drive it.

## Vocabulary

- **Track** - an audio file in the library folder.
- **Private library folder** - a library folder no other program can reach. A track arrives in one only by a peer fetch.
- **Song** - the library's record of a track: its uuid, title, artist, duration, file size, location, whether the file is currently present, and a free-form metadata blob.
- **Playlist** - a named, ordered list of songs. Duplicates are allowed. Carries its uuid, creation and modification times, and its own metadata blob.
- **Library** - every playlist, plus `All Tracks`, which core assembles from every song it knows of.
- **Queue** - the run of songs core is working through, with a cursor marking the current one. Songs behind the cursor are called the history, songs ahead are queued.
- **Queue entry** - one slot in the queue. Carries a session-scoped id, the song, and whether a client put it there or core's refill drew it.
- **Autofill** - core drawing from the source to keep the queue stocked ahead of the cursor.
- **Session** - the playback state core owns: the current song, position, volume, repeat and shuffle.

## Capabilities

- Discover tracks in the library folder and reconcile them against known songs, including relocating a song whose file has moved.
- Read and edit songs and playlists.
- Play a playlist or an arbitrary list of songs, with transport control: play, pause, seek, skip forward, skip back.
- Edit the queue while it plays: insert, remove, reorder, clear.
- Repeat and shuffle, applied as the queue refills.
- Report the session to every connected client, continuously.
- Become a peer of another core on the local network, and pull its songs and playlists.

## Documents

- [client-protocol.md](client-protocol.md) - the interface. Everything needed to write a client.
- [peer-protocol.md](peer-protocol.md) - how two cores come to trust each other, and how songs and playlists move between them.
- [core-structure.md](core-structure.md) - how core is put together internally.
- [core-data.md](core-data.md) - the database, and how tracks map onto songs.
- [core-playback.md](core-playback.md) - queue, cursor, repeat and shuffle semantics.
- [frontends.md](frontends.md) - the bundled Qt app and what it remembers between runs.
- [frontend-peers.md](frontend-peers.md) - what that app adds to browse peers and pull from them.
