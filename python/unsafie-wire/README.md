# unsafie-wire

The contract that the unsafie server and the machines in the pool both speak. No dependencies:
the machine side installs it in a second, and the server imports the same module instead of
keeping a second copy of the format.

Two things live here.

**Markers.** A command run on a machine prints ordinary text, and anything structured goes as a
single line:

```
::unsafie::{"kind":"image","blob":"shots/a1b2","mime":"image/png","caption":"landing"}
```

The server strips those lines out of the output and turns them into what the model actually sees:
an image inside the tool result, a file delivered to the chat, a note in the live log.

**Frames.** The machine channel: commands going down, output coming back, an exit code closing
the command. One JSON object per line, offsets on the transport, so a dropped connection resumes
where it stopped.
