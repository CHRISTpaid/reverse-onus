# How Suno works: findings

Researched 2026-10-12 from public sources only: Suno's own blog and help centre, interviews
with Suno's CEO, Suno's open-source Bark model, press and reviews, and the open music-model
papers and repos. Nothing was taken from Suno's private systems, no auth or rate limits were
touched, and no Suno songs were downloaded. Each claim is marked **Observed** (a source says
so), **Inferred** (my conclusion from several observations) or **Unknown**.

## 1. The product today (Observed)

| Item | Value | Source |
|---|---|---|
| Current models | `v6` (Pro/Premier, "reliable, precise"), `v6-wild` (Pro/Premier, "less predictable and more varied"), `v6-mini` (everyone, "faster, more efficient"), launched 2026-09-09 | suno.com/blog/introducing-v6 |
| Retired | every model before v6 (v4.5, v4.5+, v5, v5.5) is retired as v6 rolls out; extend/cover of old songs now runs on v6 | played.fm, suno blog |
| Licensing | v6 built with Warner Music Group, BMG and Believe; earlier retirement tied to Warner's Nov 2025 settlement | suno blog, played.fm |
| Length | up to 8 minutes in a single generation (v6, v6-wild, v6-mini); Extend goes past that | help.suno.com/en/articles/13924929 |
| Songs per request | one generation costs 10 credits and returns two songs | flexprice.io |
| Plans | Free 50 credits/day, v6-mini, 7 lifetime downloads; Pro $8/mo 2,500 credits, 20 downloads/mo; Premier $24/mo 10,000 credits, 60 downloads/mo (download caps since 2026-09-03) | played.fm |
| Field limits | Styles 1,000 chars and Exclude styles 1,000 (read from `maxlength` on the composer), simple-mode description 3,000 (v5.5), lyrics 5,000 and title 100 (community consensus, enforced server side) | hookgenius.app |
| Lyric syntax | section tags in square brackets on their own line: `[Verse 1]`, `[Chorus]`, `[Bridge]`, `[Outro]`, `[End]`; case-insensitive; descriptors after a colon `[Verse: whispered vocals, acoustic guitar only]`; `[Male Vocal]`/`[Female Vocal]`; no `[no vocals]` tag (use Instrumental + Exclude "vocals") | blakecrosley.com guide |
| Controls | Weirdness slider (Safe..Chaos) and Style Influence slider (Loose..Strong), both centred by default with no numbers shown; Exclude styles field; Duration slider (v5.5+); Audio Influence for uploads | blakecrosley.com guide |
| Editing | Extend (from a chosen point, ~30-60 s per extension in older models), Replace Section, inpainting, crop, fade; v6 adds plain-language section edits, single-lyric changes, multi-song mashups, riff sampling, image/video input | blakecrosley.com, suno blog |
| Audio in | Covers, Remixes, Add Vocals, Add Instrumentals from uploaded audio | blakecrosley.com |
| Voices | Personas (timbre from a generated song); v5.5 replaced them with Voices (verified voice cloning) | blakecrosley.com |
| Stems | Split from mix (2 stems, all tiers), Auto Split (up to 12, Pro/Premier), Advanced Split (~100 instruments, Premier) | blakecrosley.com |
| Developer API | none public: no docs, portal or SDK; enterprise access by sales only. Community wrappers replay browser session tokens, which likely breaks Suno's terms. **This project doesn't use them.** | sonilo.com (a competitor; treat with care) |

## 2. The model family underneath (Observed facts, Inferred design)

**Observed, from Suno's founders and their open model:**
- Suno's founders released **Bark** (open source), a GPT-style transformer trained
  self-supervised on broad real audio, then adapted for text-to-speech. Shulman: "there's a
  lot of code borrowed from" Karpathy's nanoGPT. (Latent Space)
- How their models work, in Shulman's words: "You have some abstract notion of a token and
  you train a model to predict the probability over all of the next token." "We prefer
  transformers." Most of the effort is "how do I tokenize audio in the right way", "at least
  similar to how it's done in the open source stuff". (Latent Space)
- Models are "still pretty small" and scale like text transformers. They care about "how many
  tokens per second we can generate" because "we need to stream you music as fast as you can
  listen to it". (Latent Space)
- On diffusion, Shulman says it gives "great sounding elevator music that's a little boring",
  while autoregression "figures it out bit by bit, which tends to make for more interesting
  music". (Amplify Partners)
- Training data: they pick little by hand ("low bit depth", "wrong sample rate" filters) and
  use human preference comparisons to steer models. (Amplify Partners) v6 is trained in
  partnership with licensed catalogues. (suno blog)

**Inferred (moderate confidence):** Suno is, at its core, an autoregressive transformer over
discrete audio-codec tokens, conditioned on style text and lyrics, decoding in real time so the
app can stream the song. Bark used the same recipe (text -> semantic tokens -> coarse codec
tokens -> fine codec tokens -> EnCodec decoder), so the most likely shape is a hierarchy of
token models plus a neural codec decoder.

**Inferred (low confidence):** the jump in fidelity from v4.5 onward suggests a stronger
acoustic stage (a better codec, or a diffusion/flow decoder on top of the token model). The
best open systems landed on exactly that split in 2026: an autoregressive planner for
structure, melody and lyrics plus a flow or diffusion stage for sound (ACE-Step 1.5: LM
planner + DiT; YuE2: AR score and semantic tokens + flow-matching latents, which beat an
LM-plus-DiT pair 53% to 36% in its ablation). Suno hasn't said which it uses.

## 3. How each feature probably works, and how the clone does it

| Suno feature | Likely mechanism (Inferred) | Clone |
|---|---|---|
| Two songs per request | two samples with different seeds | `variations=2`, seeds `s, s+1` |
| Styles / Exclude styles | text conditioning; exclude as a negative (CFG) condition | caption + negative prompt (`style.py`) |
| Weirdness | sampling temperature (Safe..Chaos) | ACE-Step `lm_temperature` 0.55..1.15 |
| Style Influence | classifier-free guidance strength | `lm_cfg_scale` 1.5..3.5, `guidance_scale` 4..10 |
| Simple mode | a lyrics/style writer turns the description into Custom-mode inputs | ACE-Step planner LM (`sample_mode`) |
| Meta tags | lyrics conditioning with structure markers | parsed into sections; descriptors move to the caption |
| Extend from T | continuation with the clip up to T as the prefix | engine repaint on clip tail + silence, keep the new part |
| Get whole song | concatenation of the extend chain | `concat` with 50 ms crossfades |
| Replace Section | infilling a time range | engine repaint, then splice so the rest stays bit-exact |
| Cover / Audio Influence | conditioning on the source's melody/structure | ACE-Step `cover`, strength 0.2..1.0 |
| Stems | a separation model on the output | Demucs if installed, else ACE-Step `extract` |
| Personas / Voices | audio prompt or speaker conditioning | not built yet (YuE ICL or ACE-Step reference audio could do it) |

## 4. Why the clone uses open models instead of training from scratch

A Suno-class model needs hundreds of thousands of hours of licensed music (YuE2 used about
346,000 hours) and a large training budget. Open models already get close: in YuE2's blind
tests it beat Suno v4.5 (57% vs 31%), tied v5 (40.4% vs 39.9%) and lost to v6 (32% vs 59%).
So, as with the Genjutsu clone, the accurate path is to rebuild Suno's product layer (inputs,
lyric syntax, sliders, extend/cover/edit/stems, two takes, API) over the best open engines.

| Engine | Licence | Fits | Edit tasks | Notes |
|---|---|---|---|---|
| **ACE-Step 1.5** (default) | MIT, commercial use OK | < 4 GB (2B turbo) to 24 GB+ (XL 4B) | text2music, cover, repaint, lego, extract, complete | 10 s to 10 min; under 10 s per song on an RTX 3090; REST server built in |
| **YuE2-3B** (`yue2`) | code open; weights CC BY-NC 4.0 (individual creators may sell songs; companies need a licence) | 24 GB GPU | generate, score edit, melody covers | best quality in public blind tests; 48 kHz stereo; no extend |
| DiffRhythm / DiffRhythm 2 | Apache 2.0 (v1) | ~8 GB | full-song diffusion | fast, weaker editing |
| MusicGen, Stable Audio Open | CC BY-NC / Stability community | 12-16 GB | instrumental only | not song generators |

## 5. Unknown

- The exact v6 architecture, codec and sample rate.
- The prompt expansion Suno applies to Styles before conditioning, and how Exclude is applied.
- What the sliders' 0..1 values do inside the model, and what `aug_creativity` controls.
- How v6 maps a plain-language section edit onto the model.
- The request shape for Get whole song.

## 6. How to settle the unknowns with REA

The web app runs in your browser, so REA can inspect the requests your own logged-in
session sends during normal use. Follow [REA_CAPTURE.md](REA_CAPTURE.md). The model key, task
names and slider fields it reveals go into `schemas.py` aliases and the slider mapping in
`backends/acestep.py`; your own downloaded songs feed the A/B harness (`suno-clone ab`).

## 7. Observed in a capture of the user's own session (2026-10-13)

Recorded with Chrome DevTools in the user's own signed-in Chrome while they made songs, saved
with "Copy all as HAR (sanitized)", cleaned of cookies, auth headers and token fields, then
summarised with REA (695 requests). Request bodies only: that export has no response bodies.

| Item | Observed |
|---|---|
| Generate endpoint | `POST studio-api-prod.suno.com/api/generate/v2-web/` for every generation, extend and cover |
| Model key | Custom, Extend and Cover sent `"mv": "chirp-hawk"`, `"generation_type": "TEXT"` (v6, confirmed by the third capture) |
| Custom mode | `title`, `tags` (Styles), `negative_tags` (Exclude styles), `prompt` (lyrics), `make_instrumental`, `metadata.create_mode: "custom"` |
| Sliders | `metadata.control_sliders = {weirdness_constraint: 0.23, style_weight: 0.64, aug_creativity: 1}`: Weirdness and Style Influence are sent on a 0..1 scale, the scale the clone already uses |
| Extend | `"task": "extend"`, `continue_clip_id`, `continue_at` in seconds (131), `metadata.is_remix: true`, `metadata.lyrics_updated: false` |
| Cover | `"task": "cover"`, `cover_clip_id`, `metadata.is_remix: true` |
| Other body fields | `persona_id`, `artist_clip_id` / `artist_start_s` / `artist_end_s`, `continued_aligned_prompt`, `override_fields`, `user_uploaded_images_b64`, `transaction_uuid`, `lyrics_project_id`, `metadata.is_max_mode`, `is_mumble`, `disable_volume_normalization`, `create_surface`, `user_tier`, plus an anti-bot `token` / `token_provider` / `create_session_token` (redacted) |
| Other endpoints | `/api/feed/v3` (polling for results), `/api/lyrics-projects` (+ `/flush`), `/api/gen/{id}/aligned_lyrics/v3`, `/api/gen/{id}/waveform-aggregates`, `/api/video/generate/{id}/status/` |

**Second capture (same day, with Suno's replies where Chrome kept them):**

| Item | Observed |
|---|---|
| Simple mode | same endpoint; `"task": "agentic_thinking"`, `"mv": "chirp-goose"`, empty `prompt`, the description in `gpt_description_prompt`, `metadata.create_mode: "simple"`, `is_speech: true`, `lyrics_model: "default"`. The lyrics are written server side by a separate lyrics model |
| Stems | `"task": "gen_stem"`, `"mv": "chirp-v3-5-b"`, `make_instrumental: true`, `continue_clip_id` (the source), `stem_type_id: 91`, `stem_type_group_name: "Twelve"`, `stem_task: "twelve"`; then `/api/gen/{id}/convert_wav/`, `/api/download/authorize`, `/api/studio/create-project`. Stems are made by a generation model, not a plain separator |
| Model names in replies | `chirp-fenix` = v5.5, `chirp-flounder` = v5.5 upsampling, `chirp-goose` = v6 (seen on Simple/agentic songs); full list after the third capture below |
| Task values in replies | `cover`, `vox_cover`, `artist_cover`, `vox`, `upsample`, `agentic_thinking` |
| Clip shape (`/api/feed/v3`) | `id`, `status` ("complete"), `model_name`, `major_model_version`, `title`, `image_url`, `video_url`; audio in `media_urls` as a CloudFront `.m4a` (Opus, progressive); `metadata` holds `type` (gen / upload / upsample), `task`, `tags`, `negative_tags`, `prompt`, `gpt_description_prompt`, `duration` (s), `control_sliders`, source ids (cover, edited, artist, upsample), `persona_id`, `has_vocal`, `has_stem`, `is_remix`, `is_speech`, `vox_render_mode`, min/max/avg BPM |

**Third capture (replies kept):**

| Item | Observed |
|---|---|
| Replace Section | same endpoint; `"task": "infill"`, `"mv": "chirp-hawk"`, `continue_clip_id`, `prompt` = the full lyrics, `metadata.infill_lyrics` = the new section's lyrics, `infill_start_s: 114.8`, `infill_end_s: 144.8`, `infill_dur_s: 30`, `infill_context_start_s: 99.8`, `infill_context_end_s: 159.8` (15 s of the song either side) |
| Infill result | reply adds `include_history_s: 2.0`, `include_future_s: 2.0`; each new clip is 34 s (the section plus 2 s margins), spliced into the song by the web app |
| Remaster | `POST /api/generate/upsample` with `clip_id`, `"model_name": "chirp-halibut"`, `"variation_category": "normal"`, `"style_profile": "boost"`; returns 2 clips titled "&lt;title&gt; (Remastered)" |
| Lifecycle | generate replies with 2 clips, `status: "submitted"`, empty `audio_url`; `/api/feed/v3` then shows submitted, queued, streaming, complete; `duration` appears only at complete; audio is the CloudFront `.m4a` in `media_urls` |
| Model keys (confirmed from replies) | `chirp-auk` v4.5, `chirp-crow` v5, `chirp-fenix` v5.5, `chirp-flounder` v5.5 upsampling, `chirp-hawk` v6 (Custom, Extend, Cover, Replace Section), `chirp-halibut` v6 remaster, `chirp-goose` v6 Simple mode; `chirp-v3-5-b` (stems) is probably v3.5 by its name, unconfirmed |

Inferred from these: v6 is a family of separately named models for generation, simple-mode
planning, remastering and stems, and the editing tasks (extend, infill, cover) all run on the
main generator with audio context rather than on separate edit models. Still not captured:
Get whole song.

What this changes in the clone: the request models accept these keys,
`POST /api/generate/v2-web/` takes a web-app-shaped body as is (generate, simple, extend,
cover, infill, gen_stem), Replace Section now sends the engine 15 s of context either side and
crossfades over 2 s margins like Suno's infill, and `GET /api/feed/v3` returns clips in the same shape Suno's feed does
(`suno_compat.py`). Timestamped
lyrics (`aligned_lyrics`) and waveform previews are features the clone doesn't have yet.

## Sources

- The user's own session capture, 2026-10-13 (kept on their PC, not in this repo)
- https://suno.com/blog/introducing-v6
- https://help.suno.com/en/articles/13924929
- https://played.fm/blog/suno-v6-review
- https://blakecrosley.com/guides/suno
- https://hookgenius.app/learn/suno-character-limits/
- https://flexprice.io/pricing-index/suno
- https://latent.space/p/suno
- https://amplifypartners.com/barrchives/how-suno-builds-ai-models-for-musicians
- https://sonilo.com/blog/guides/official-suno-api-saas-builders-2026
- https://github.com/ace-step/ACE-Step-1.5 (docs/en/API.md, docs/en/INFERENCE.md)
- https://huggingface.co/m-a-p/YuE2-3B
- https://neurohive.io/en/state-of-the-art/yue2-open-source-ai-song-generator/
- https://github.com/multimodal-art-projection/YuE
- https://songcreator.pro/blog/best-open-source-ai-music-models
- https://www.spheron.network/blog/deploy-open-source-ai-music-generation-gpu-cloud-2026/
