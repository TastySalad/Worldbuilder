# World Builder

A LangGraph-powered world-building engine that generates interconnected lore as Obsidian-ready Markdown. Each entity is a note with `[[wiki-links]]`, taxonomy tags, and a shared chronicle for continuity.

## Setup

1. **Python 3.10+** and a virtual environment:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   # source .venv/bin/activate   # macOS / Linux
   pip install -r requirements.txt
   ```

2. **API key** — create a `.env` file in the project root:

   ```
   GEMINI_API_KEY=your_key_here
   ```

   The engine uses Google Gemini (`gemini-2.5-flash`) via LangChain.

## Running `main.py`

All generated assets are written to `output/` as Markdown files.

### Create an entity

```bash
python main.py --region "The Glimmering Wastes"
python main.py --city "Aqua Magna Outpost" --context "The Glimmering Wastes"
python main.py --character "Sandworm" --context "The Glimmering Wastes"
python main.py --faction "The Iron Shield" --context "Oakhaven"
```

**Entity types:** `region`, `city`, `character`, `faction`, `guild`, `phenomena`, `institution`, `lineage`, `economy`, `flora_fauna`, `artifact`, `event`, `lore`

| Flag | Description |
|------|-------------|
| `--context "Parent"` | Parent region or city (required for most non-region types) |
| `--mode exploratory\|isolated\|fill` | Generation mode (default: `exploratory`) |
| `--inspiration "X"` | Thematic reference (e.g. `"Kenshi"`, `"Cyberpunk"`) |
| `--expand N` | Auto-generate up to N missing `[[wiki-links]]` |
| `--migrate` | Audit and repair all existing assets on disk |

### Generation modes

- **exploratory** (default) — Create new lore and discover new `[[wiki-links]]` to expand the graph.
- **isolated** — Rewrite an existing asset without spawning new linked entities.
- **fill** — Flesh out missing links from the backlog without adding new branches.

### Examples

```bash
# Thematic region with inspiration research
python main.py --inspiration "Dune" --region "The Shifting Sands"

# Expand 5 uncreated wiki-links
python main.py --expand 5

# Rewrite an existing character without new locations
python main.py --mode isolated --character "Barnaby"

# Audit and normalize all files on disk
python main.py --migrate
```

### How it works

`main.py` runs a small LangGraph pipeline:

1. **Supervisor** — Classifies the request and enforces parent hierarchy (cities need regions, characters need a home, etc.). If a parent is missing, it builds the parent first.
2. **Inspiration Researcher** — Optional thematic research when `--inspiration` is used.
3. **Generic Builder** — Generates lore anchored to a parent context.
4. **Continuity Validator** — Checks output against `output/world_chronicle.md`, appends new facts, and writes the final note.

Each note gets a `#type/...` tag (e.g. `#type/region`, `#type/city`) and normalized `[[wiki-links]]` that match filenames in `output/`.

## The skill (`WORLD_BUILDING_SKILL.md`)

[`WORLD_BUILDING_SKILL.md`](WORLD_BUILDING_SKILL.md) is not a Cursor agent skill (he lied I created it to gemini CLI) that translates natural-language requests into the correct `main.py` commands. It encodes the hierarchy rules, mode selection, and command syntax so you can say things like *"Add a shady tavern owner named Barnaby to Arrakeen Outpost"* instead of memorizing flags.

### Using the skill in Cursor (or in general)

**Option A — Reference in chat**

Mention or `@`-reference `WORLD_BUILDING_SKILL.md` when asking the agent to build or edit your world. The agent will read the skill and run the appropriate terminal commands.

**Option B — Persistent rule**

Copy or symlink the skill into `.cursor/rules/` (or add a project rule that points to it) so every agent session follows the same command mapping and hierarchy constraints.

### What the skill enforces

- **Hierarchy** — Regions are root anchors; cities, characters, and factions must declare a parent.
- **Mode selection** — Exploratory for new growth, isolated for edits, fill for backlog resolution.
- **Command mapping** — Natural language → `python main.py --[type] "Name" --context "Parent" --mode ...`

## Loading output in Obsidian

Generated notes are standard Markdown with Obsidian wiki-links. The `output/` folder can be opened directly as an Obsidian vault.

1. Open **Obsidian**.
2. Click **Open folder as vault** (or *Open another vault* → *Open folder as vault*).
3. Select the `output/` directory inside this project (e.g. `c:\Users\Salad\world-builder\output`).

Obsidian will pick up:

- **`[[wiki-links]]`** — Clickable links between entities; the graph view shows how your world connects.
- **`#type/...` tags** — Filter or search by entity type in the tag pane.
- **Existing vault config** — `output/.obsidian/` already includes graph, backlink, and tag plugins.

### Tips

- Use the **Graph view** to explore regions, cities, factions, and how they link together.
- Use **Backlinks** on any note to see what references it.
- After generating new content with `main.py`, Obsidian usually picks up new files automatically; use *Reload app without saving* if a note does not appear.
- `world_chronicle.md` is the master continuity ledger — useful for reading established facts, but most browsing happens through linked entity notes.

## Project layout

```
world-builder/
├── main.py                  # World-building engine
├── WORLD_BUILDING_SKILL.md  # Cursor agent skill
├── requirements.txt
├── .env                     # GEMINI_API_KEY (not committed)
└── output/                  # Generated Obsidian vault (gitignored)
    ├── .obsidian/
    ├── world_chronicle.md
    └── *.md                 # Entity notes
```
