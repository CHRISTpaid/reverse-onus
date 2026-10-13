# Getting started

This guide takes you from nothing to making your first song. Everything runs on your own
computer. You don't need an account, a sign-up, a domain name or an internet connection
after setup (the first start downloads the music models).

reverse-onus has two parts that run side by side:

1. **ACE-Step**, the open-source music model. It runs on your graphics card and makes the audio.
2. **reverse-onus**, the studio page you use in your browser. It turns your lyrics and styles
   into requests for ACE-Step and keeps your songs.

## What you need

- **A graphics card.** An NVIDIA card on Windows or Linux, or an Apple Silicon Mac (M1 or
  newer). ACE-Step can run in under 4 GB of video memory with its smallest settings, but 8 GB
  or more is much more comfortable. See [No suitable graphics card?](#no-suitable-graphics-card)
  if you don't have one.
- **Disk space** for the models, which download automatically the first time ACE-Step starts.
- **An up-to-date graphics driver.** On Windows the ACE-Step package needs CUDA 12.8, which
  comes with a current NVIDIA driver.

## Step 1: Install and start ACE-Step

### Windows

1. Download the portable package:
   [ACE-Step-1.5.7z](https://files.acemusic.ai/acemusic/win/ACE-Step-1.5.7z). Everything it
   needs is already inside.
2. Create an empty folder with plenty of free space, for example `C:\ACE-Step-1.5`, and
   extract the package into it with [7-Zip](https://www.7-zip.org/). The archive has no folder
   of its own, so its files land straight in the folder you pick.
3. Open that folder and double-click **`start_api_server.bat`**.
   (AMD graphics cards use `start_api_server_rocm.bat` instead.)
4. Leave the black window open. The first start downloads the models and can take a while.
   It's ready when you can open http://localhost:8001/health in your browser.
5. If the window shows error 1455 or "paging file is too small", see
   [Troubleshooting](#troubleshooting).

### Mac (Apple Silicon)

1. Download the portable package:
   [ACE-Step-1.5.zip](https://files.acemusic.ai/acemusic/mac/ACE-Step-1.5.zip) and unzip it.
2. Open Terminal in that folder and run:
   ```sh
   chmod +x start_api_server_macos.sh
   ./start_api_server_macos.sh
   ```
3. Leave Terminal open. It's ready when http://localhost:8001/health opens in your browser.

### Linux (or installing from source anywhere)

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh        # installs uv, a Python package manager
git clone https://github.com/ACE-Step/ACE-Step-1.5.git
cd ACE-Step-1.5
uv sync
uv run acestep-api                                      # REST API on http://localhost:8001
```

ACE-Step's own [installation guide](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/INSTALL.md)
covers AMD, Intel and CPU-only setups and every setting.

## Step 2: Install reverse-onus

reverse-onus needs **Python 3.10 or newer**, **Git** and **ffmpeg**.

### Windows

Open **PowerShell** and install the three tools (skip any you already have):

```powershell
winget install Python.Python.3.12 Git.Git Gyan.FFmpeg
```

Close PowerShell and open a new one so it finds them, then:

```powershell
git clone https://github.com/CHRISTpaid/reverse-onus
cd reverse-onus
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[mcp]"
```

If PowerShell refuses to run `activate`, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

### Mac

With [Homebrew](https://brew.sh/):

```sh
brew install python git ffmpeg
git clone https://github.com/CHRISTpaid/reverse-onus
cd reverse-onus
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[mcp]"
```

### Linux (Debian or Ubuntu)

```sh
sudo apt install python3 python3-venv git ffmpeg
git clone https://github.com/CHRISTpaid/reverse-onus
cd reverse-onus
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[mcp]"
```

## Step 3: Open the studio

With ACE-Step still running, run this inside the `reverse-onus` folder:

```sh
reverse-onus serve --engine acestep
```

Then open **http://localhost:8000** in your browser. The engine badge in the corner should
say **ACE-Step 1.5**.

To make a song:

1. Pick **Custom**, write lyrics with tags like `[Verse]` and `[Chorus]` (the buttons under the
   box add them), and describe the sound under **Styles**, for example
   `indie folk, warm acoustic guitar, female vocals`.
   Or pick **Simple** and just describe the song.
2. Press **Create**. You get two takes. They appear in your workspace when they're done.
3. Press play, or open a song's **⋯** menu to extend it, cover it in another style, replace a
   section, split stems or download it.

Your songs are saved in a `ReverseOnus` folder in your home folder, one folder per song. To save
them somewhere else, set `REVERSE_ONUS_WORKDIR` to that folder before starting.

Song length is chosen by the model unless you set one. The same short lyric can come out at
45 seconds or 3 minutes, so set **Length** under **More options** if you want a particular length.

On a fast card it's quick: on an RTX 4090 two takes of a song took about 26 seconds once the
models had loaded.

## Every time after that

You only install once. Each time you want to make music, start two things:

1. ACE-Step: double-click `start_api_server.bat` (Windows), or run the start script on Mac or
   `uv run acestep-api` on Linux.
2. reverse-onus: open a terminal in the `reverse-onus` folder, activate the environment
   (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on Mac and Linux), then run
   `reverse-onus serve --engine acestep` and open http://localhost:8000.

## Use it from an AI assistant instead

reverse-onus also works as a tool for Claude Code, Claude Desktop, Codex and ChatGPT, so you can
ask for a song in plain words and the assistant writes the lyrics and makes it. ACE-Step still
needs to be running. Setup for each assistant is in the
[README](../README.md#three-ways-to-use-it).

## No suitable graphics card?

- **Rent one.** Run ACE-Step on a cloud GPU (RunPod, Vast.ai, Lambda and similar), then point
  reverse-onus at it: set `ACESTEP_URL` to that machine's address before running
  `reverse-onus serve --engine acestep`. If you protect that server with ACE-Step's API key,
  set `ACESTEP_API_KEY` too.
- **Just look around.** `reverse-onus serve` with no engine uses a demo engine that makes test
  tones. It's useful for trying the page, but it doesn't make real music.

## Troubleshooting

| What you see | What to do |
|---|---|
| ACE-Step's window shows Windows error 1455 or "the paging file is too small" while loading | Its language model ran out of Windows virtual memory, even on PCs with plenty of RAM. In the ACE-Step folder, copy `.env.example` to `.env` (if there's no `.env` yet), add the line `ACESTEP_LM_BACKEND=pt`, and start `start_api_server.bat` again. Making the Windows paging file bigger also fixes it. |
| A song fails with "Can't reach ACE-Step" | ACE-Step isn't running or hasn't finished loading. Start it (Step 1) and wait until http://localhost:8001/health opens. |
| "ffmpeg is required" | Install ffmpeg (Step 2), then open a new terminal. |
| `reverse-onus` is not recognised as a command | Activate the environment first: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Mac, Linux). |
| The engine badge says "Demo engine" | You started it without `--engine acestep`. |
| The first start or first song takes a long time | ACE-Step downloads and loads its models the first time. Later songs are much faster. |
| ACE-Step runs out of graphics memory | Use smaller models. ACE-Step's guide lists which models fit which cards; set them in its `.env` file (`ACESTEP_CONFIG_PATH=acestep-v15-turbo`, `ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-0.6B`). |
| Simple mode writes lyrics in the wrong language | Name the language in your description, for example "an upbeat pop song about summer, in Spanish". With no language named, reverse-onus asks for English. |
| Simple mode fails on a small card | Simple mode needs ACE-Step's language model, which is switched off on cards with 6 GB or less. Use Custom mode, or a bigger card. |
| Port 8000 is already in use | Pick another: `reverse-onus serve --engine acestep --port 8080`, then open http://localhost:8080. |

## Updating

```sh
cd reverse-onus
git pull
pip install -e ".[mcp]"
```

ACE-Step updates separately. Its Windows package includes `check_update.bat`.

## Command line

Every command takes `--engine acestep`, for example:

```sh
reverse-onus generate --engine acestep --style "indie folk, female vocals" --lyrics song.txt --duration 90
```

The full list of commands is in the [README](../README.md#three-ways-to-use-it).
