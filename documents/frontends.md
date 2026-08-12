# frontends

A frontend is a client. It talks to core through `CoreClient` and holds no library or playback state of its own, only what it needs to draw. The bundled one is PyQt6, in `frontends/qt`, and calls `CoreService` in-process.

## The queue pane

The pane renders `QueueState` as it arrives. Entries ahead of the cursor split at the origin boundary, `user` entries drawn at full weight and the `autofill` tail dimmed, so what was asked for reads apart from what core guessed. 
Removal sends the selected entry ids. See [client-protocol.md](client-protocol.md) for the queue commands themselves.
