# Issue tracker: Local Markdown

Issue tickets for this repo live as markdown files in `.scratch/`. **Formal specs (SDD) are NOT here** — they live in `specs/SNNN-*/` per `CLAUDE.md` §0; a `.scratch/` effort that matures into formal implementation graduates its decisions to a `specs/SNNN-*/spec.md`. `.scratch/` is the AFK work-queue / research-ticket layer only.

## Conventions

- One effort per directory: `.scratch/<effort-slug>/`
- Implementation issues are one file per ticket at `.scratch/<effort-slug>/issues/<NN>-<slug>.md`, numbered from `01` — never a single combined tickets file
- Triage state is recorded as a `Status:` line near the top of each issue file (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new issue file under `.scratch/<effort-slug>/issues/` (creating the directory if needed). Do NOT create a `spec.md` here — if the work needs a formal spec, open one in `specs/SNNN-*/` instead.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` — the Notes / Decisions-so-far / Fog body.
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
