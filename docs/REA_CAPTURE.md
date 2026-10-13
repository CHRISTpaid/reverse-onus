# Reading Suno's request fields with REA (your own browser session)

Suno's models run on Suno's servers, so nothing can pull their weights. What REA *can* do is
inspect the requests the Suno web app sends from **your own logged-in browser** while you use
it normally. That shows the model key, task names, slider fields and how Extend, Cover and
Replace Section are expressed. Capture only your own traffic for things you'd make anyway, and
don't replay the requests: the clone never talks to Suno.

## 1. Record a HAR

1. Open https://suno.com/create in Chrome and sign in.
2. Open DevTools (F12) > Network. Tick **Preserve log**. Clear the list.
3. Do one of each, waiting for the songs to finish:
   - Custom mode: lyrics with tags, Styles, Exclude styles, move both sliders off centre.
   - Simple mode: a song description.
   - Extend one of the results from a mid-song timestamp, then "Get whole song".
   - Cover (or Remix) of one result, and a Replace Section if your plan has it.
4. In the Network tab, click the download-arrow button on the toolbar (**Export HAR**) and save
   it as `suno.har`. Recent Chrome only offers "Copy all as HAR (sanitized)" on right-click,
   which copies to the clipboard and leaves out every response body, so prefer the toolbar
   button. Either way, strip cookies, auth headers and token fields before sharing, and keep
   the file private: it holds your lyrics.

Use your normal signed-in Chrome. A browser that a script controls (Playwright, Selenium)
can't sign in with Google.

## 2. Inspect it with REA

```sh
npx -y rea-agents@latest inspect-web-network-capture /absolute/path/suno.har har --json > rea.json
python scripts/har_digest.py rea.json
```

rea-agents 6.4 needs Node 24 or newer; with an older Node, run it through `npx -p node@24`.

REA validates the HAR, keeps each record's provenance and redacts sensitive values.
`har_digest.py` prints only the generation-related requests and the fields that matter, then
lists every model/task value it saw.

With an agent (after `npx rea-agents setup`): "Inspect suno.har with
inspect_web_network_capture. Which request submits a generation? List every field in its body,
the model key, the task names used for extend, cover and replace section, and the slider fields."

## 3. What to look for

| Field or value | What it settles |
|---|---|
| a model key (`mv`, `model`, `major_model_version`, a `chirp-*` codename) | which internal model id maps to v6 / v6-wild / v6-mini |
| `tags`, `negative_tags`, `prompt`, `gpt_description_prompt`, `make_instrumental` | field names to alias in `schemas.py` (some are already accepted) |
| slider fields (`weirdness`, `style_weight`, `audio_weight` or similar) and their numbers | the real numeric range of Weirdness / Style Influence / Audio Influence, to correct `backends/acestep.py` |
| `task`, `continue_clip_id`, `continue_at`, `infill_*`, `cover_clip_id` | how extend, replace section and cover are sent |
| response `audio_url`, `stream*`, `duration`, `metadata` | streaming behaviour, output format, the lyrics/style Suno actually used after any prompt expansion |

Send me `rea.json` (or the digest output) and I'll fold the confirmed facts into the clone.
For quality, download a few of your own songs and list them in a `cases.json` for
`suno-clone ab` (README, "Measuring against Suno").
