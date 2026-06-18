# Forza Designer 6+ (FD6)

<p align="center">
  <img src="tools/SplashScreen.gif" alt="Forza Designer 6 splash" width="600"/>
</p>

<p align="center">
  <a href="https://youtu.be/8LGvE7O9aeg">
    <img src="https://img.youtube.com/vi/8LGvE7O9aeg/maxresdefault.jpg" alt="Watch the FD6 trailer" width="600"/>
  </a>
  <br/>
  <sub><a href="https://youtu.be/8LGvE7O9aeg">▶ Trailer / tutorial on YouTube</a></sub>
  <br/>
  <sub><a href="https://github.com/tokyubevoxelverse/ForzaDesignerRadioMaker/releases/tag/0.0.1-Alpha">🎵 Forza Designer Radio Maker — v0.0.1-Alpha release</a></sub>
</p>

<p align="center">
  <img src="Pink.png" alt="FD6 badge" width="128"/>
</p>

> Convert any image into a vinyl group for **Forza Horizon 3, 4, 5, or 6**, or into a livery for **Assetto Corsa Competizione**.

**Repo:** https://github.com/tokyubevoxelverse/ForzaDesigner6 · **License:** MIT · **Windows 10/11 x64**

---

## Install

1. Download `FD6.exe` from [Releases](https://github.com/tokyubevoxelverse/ForzaDesigner6/releases).
2. Double-click — no installer, use admin rights. Windows SmartScreen → "More info" → "Run anyway".

Source build: Python 3.10+, `pip install -r requirements.txt`. Microsoft Visual C++ Redistributable is normally already installed; if FD6 fails to launch, grab it [here](https://aka.ms/vs/17/release/vc_redist.x64.exe).

---

## Updates & Discord

### In-app updates (Discord members only)
FD6 can update itself, but **in-app updates require being a member of the FD6
Discord server**. This keeps the community together — everyone who updates
through the app is in the Discord.

1. On first launch (and after each new version) a **Welcome** panel offers
   **Link Discord**, **Check for updates**, or **Skip**.
2. **Link your Discord** (PKCE OAuth — no bot, no password, no client secret; it
   only reads your username and which servers you're in) and join the
   [FD6 Discord server](https://discord.gg/PJFWdykGmS).
3. Once you're linked **and** a member of the server, FD6 checks GitHub on launch
   and — when a newer release exists — shows *"Update X available — install
   now?"*. Accepting downloads the new build, swaps it in, and relaunches
   automatically. **Help → Check for updates** does the same on demand.

**Not in the Discord? You update manually.** Both the automatic launch check and
the manual *Help → Check for updates* are gated behind Discord link + server
membership. If you're not linked / not a member, FD6 points you to the
[GitHub releases page](https://github.com/tokyubevoxelverse/ForzaDesigner6/releases)
to download the latest version yourself. The rest of the app works fully either
way. (If you're offline, the check simply reports it couldn't reach Discord/GitHub
and the app keeps running.)

You can link / unlink any time from **Help → Discord & auto-updates**.

### Discord Rich Presence (optional)
Toggle **"Show \"Using Forza Designer 6\" on my Discord"** in
**Help → Discord & auto-updates** to broadcast that you're using FD6 on your
Discord profile while the app is open. It's off by default, runs entirely in the
background (never blocks the app), and silently does nothing if Discord isn't
running.

---

## How to use

**Generate:**

1. Launch `FD6.exe`. Click **Upload Image…** and pick a JPEG/PNG. You can queue several images at once — each generates in turn, and each finished row gets its own **Download JSON** button.
2. Right panel: pick a **Profile** (`balanced` recommended) and **Stop at shapes** (1500 or 3000 typical). Optionally set **Compute** to **GPU** — FD6 uses cross-vendor OpenCL (NVIDIA / AMD / Intel via your graphics driver) and falls back to CPU automatically if no GPU is usable.
3. Click **Start**. Watch the live preview rebuild your image. The JSON auto-saves next to your source image when done.

**Inject:**

1. Launch your target game (**Forza Horizon 3, 4, 5, or 6**) and open the Vinyl Group editor.
2. Load a vinyl group with **at least N spheres**, where N is the shape count of your JSON. Keep saved 1500-sphere / 3000-sphere templates for reuse — fastest path is a fresh untouched template.
3. In FD6: pick your target from the **Target** dropdown, click **Upload JSON**, then **Inject into [game]**.
4. Watch the dialog progress. **Do not click anything in FD6 or the game during injection** — interacting can reallocate the in-game memory mid-write and fail the operation.
5. When the status turns 🟢 green, the vinyl group has been painted with your shapes.

**Re-injecting onto an already-painted template** works too — the locator falls back to an RTTI vtable scan when the fresh-sphere fingerprint misses. Expect an extra 2–5 minutes on the first re-injection scan per game session; subsequent ones are instant.

---

## Assetto Corsa Competizione

ACC support is **file-based** — no live memory injection. FD6 writes a two-file pair (livery `.json` + skin folder with the PNG textures) directly into ACC's user-data directory, and the in-game livery picker reads it on next launch.

1. Pick a target **car** from the ACC tab (FD6 ships a catalog of every base-game car). The catalog drives which texture slots are available.
2. **Upload Image…** to load the artwork you want printed on the car. FD6 currently writes the source PNG into the upper-left of the car's 4096×4096 livery sheet. UV-aware decal placement per car model is planned for v0.3.6.
3. Click **Export**. FD6 writes:
    - `Documents/Assetto Corsa Competizione/Customs/Cars/<car>/<livery>.json` — the metadata ACC's picker indexes.
    - `Documents/Assetto Corsa Competizione/Customs/Liveries/<livery>/decals.png` (plus `sponsors.png`) — the actual texture assets.
4. Launch ACC → Car Picker → Customs tab. The new livery appears immediately.

ACC export does not require ACC to be running and does not touch ACC's process memory — it's a pure file write to your Documents folder, so the ban-risk caveats that apply to Forza injection do **not** apply here.

---

## ✅ Do / ❌ Don't

- **Do** open the game's vinyl editor *before* clicking Inject.
- **Do** keep one or two sphere templates saved for fast re-use.
- **Do** wait for the green status — large-game scans can take minutes.
- **Do** run FD6 as admin.
- **Don't** edit, add, delete, or move shapes in-game during an active injection.
- **Don't** click anything in FD6 during the RTTI fallback phase. Windows may label it "Not Responding"; it isn't — let it finish.
- **Don't** close the game mid-injection.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Splash video hangs | Click anywhere or press Esc. A hard 30 s auto-skip is always active. |
| "No confident match" error | Vinyl editor not open, or template doesn't have enough spheres for the JSON's shape count. Load a bigger template. |
| Re-injection scan looks stalled | RTTI fallback phase can run silently for 2–5 min on a large game. The dialog resumes once a candidate is located. |
| Shapes offset or wrong scale | File an issue with the JSON, the source image, and a screenshot of the in-game result. |
| Game patched, all candidates rejected | The per-game struct offset may have shifted. You can re-probe with `python -m fd6.inject` and drop the corrected offsets into a local `.fd6_offsets.json` (see `fd6_offsets.example.json`) to fix it without rebuilding — or open an issue so the profile in `fd6/inject/game_profiles.py` can be updated. |

---

## Build from source

```powershell
git clone https://github.com/tokyubevoxelverse/ForzaDesigner6.git
cd ForzaDesigner6
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m fd6                # run from source
pytest                       # run tests
.\build_exe.bat              # → dist/FD6.exe
```

---

## Credits

Inspired by:

- **forza-painter** by `the_adawg` (FH4/FH5 — MIT)
- **geometrize-lib** by Sam Twidale (MIT)
- **Primitive** by Michael Fogleman (MIT)
- **bvzrays**' publicly available [forza-painter-fh6](https://github.com/bvzrays/forza-painter-fh6) (MIT). FD6 uses his published research for: the CLiveryGroup struct field offsets, the (X, −Y) position convention and 63 / 127 scale divisors, the confirmation that FH5 and FH6 share the same struct layout (which made FH3/FH4/FH5 support feasible), and the MSVC RTTI vtable-scan locator approach (FD6's `rtti_locator.py` looks up `.?AVCLiveryGroup@@` by C++ type). FD6 does **not** ship or load community-distributed `forza-codes.dat` runtime pattern files — only the single baseline RTTI class name is hardcoded.

The FH6 vinyl-group memory layout was independently reverse-engineered from scratch for this project against FH6 build 354.221 and later cross-validated against bvzrays' research; the two derivations matched on every field offset. The sphere-template injection workflow (load a fresh sphere group → fingerprint-locate it in memory → overwrite each sphere's bytes in place) and the strict 5/5 + 95% full-table validation gate are FD6 originals; both stay as the **primary** locator path, with RTTI vtable scan as the **secondary** fallback for re-injection onto already-painted templates.

---

## Disclaimer

**Use entirely at your own risk.** FD6 modifies the memory of a running Forza Horizon process to populate vinyl-group shapes. It does not patch the game executable, install drivers, modify save files, or attempt to bypass any anti-cheat or DRM system. However, **memory modification of a live game process may be interpreted by Microsoft, Xbox Live, or the game's publisher (Turn 10 / Playground Games) as a violation of the Microsoft Services Agreement, the Xbox Community Standards, or the relevant Forza title's terms of use. Doing so may result in temporary suspension or permanent ban of your Xbox / Microsoft account, loss of access to purchased games, online services, achievements, and any content created with FD6.**

The authors and contributors of Forza Designer 6 **accept no responsibility or liability whatsoever** for any consequences arising from the use of this software. By downloading, building, installing, or running FD6 you acknowledge these risks and accept them in full. This tool is provided as-is, MIT-licensed, with no warranties of any kind. Not affiliated with, endorsed by, or sponsored by Turn 10 Studios, Playground Games, Microsoft, Xbox, or any official Forza brand.

## License

[MIT](LICENSE) — free for any use with attribution.
