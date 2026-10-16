# Circadian

Circadian notices when a Cursor coding session is getting worse and writes a handoff for a fresh session. It runs as project hooks in this repo. A call shows up in the chat with the handoff path. You open the next session and point it at that file.

## Try it

Hooks are already in `.cursor/hooks.json`. Open this folder in Cursor. If the Hooks settings tab does not list `trace.py`, reload the window.

Start a new Agent chat and paste this:

```
Create scratch/demo/fail.py with a script that exits 1. Then run this command exactly, three times. Do not change the command. Do not fix the script.

python3 scratch/demo/fail.py

After the third run, stop.
```

When that agent stops, Cursor posts the notice as the next message in the chat:

```
Circadian reset. repeated failed commands. Earlier 0/2. Later 2/2. Open a new Cursor session and point it at .circadian/handoffs/<file>.md
```

The same file is on disk under `.circadian/handoffs/`. Open a new Agent chat and tell it to read that file.

One or two failures of that command stay quiet. So does a session that only re-reads files at a steady pace.

## Tests

```
python3 -m unittest discover -s tests -q
```
