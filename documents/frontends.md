# frontends

A frontend is a client. It talks to core through `CoreClient` and holds no library or playback state of its own, only what it needs to draw. The bundled one is PyQt6, in `frontends/qt`, and calls `CoreService` in-process.

[frontend-peers.md](frontend-peers.md) covers browsing peers, pulling from them, and admitting them.

## Features

The frontend takes `features` from the `get_state` it calls on attach and holds it for the run. `private_library` changes what the forget confirmation says, since forgetting a song on such a core deletes its file.

## Settings

The settings button in the title bar opens a dialog with one page per section. It fills the pages from `get_settings` each time it opens.

- Playback holds `shuffle_method`, offered as `True random` and `Avoid repeats`, and the starting volume.
- Save sends `update_settings` with the fields whose editor changed, and shows a refusal from core beside the buttons.
- A saved change to a field in `restart_required` is listed as needing a restart.

## The queue pane

The pane renders `QueueState` as it arrives. Entries ahead of the cursor split at the origin boundary, `user` entries drawn at full weight and the `autofill` tail dimmed, so what was asked for reads apart from what core guessed. 
Removal sends the selected entry ids. See [client-protocol.md](client-protocol.md) for the queue commands themselves.
