[English](README.md) · [繁體中文](README.zh-TW.md)

# Listen-Claude（聽聲即克）

把 Claude Code 的回應變成語音播出來。Claude 回完話自動觸發 — 邊看邊聽,擴大人機互動的輸入頻寬。

跟 [Kaikou-Claude](https://github.com/GeniusPudding/Kaikou-Claude)（語音 → Claude）對稱;本專案是 Claude → 語音。

## 特色

- **自動觸發** — Claude Code 的 `Stop` hook,Claude 回完話就播,完全免互動。
- **四種 TTS 引擎** — 免費神經網路 (Edge)、OS 內建、純離線 (Piper)、頂級雲端 (ElevenLabs)。
- **即時切換朗讀詳細度** — `/listen <mode>` 隨時在簡答/詳答之間切。
- **跳過廢話** — 太短的回應（如 "ok"）不念。
- **多視窗排隊** — 多個 Claude session 不會疊音播放。

## 平台支援

| 平台 | 預設引擎 | 狀態 | 備註 |
|------|---------|------|------|
| Windows | Edge TTS | **穩定** | 也可用 `system` 引擎走 SAPI |
| macOS | Edge TTS | **穩定** | 也可用 `system` 引擎走 `say` |
| Linux | Edge TTS | **穩定** | MP3 播放需裝 `mpg123`(edge / elevenlabs 引擎用) |

## 安裝

每個平台都一行(clone + 跑 install):

```bash
git clone https://github.com/GeniusPudding/Listen-Claude.git
cd Listen-Claude
.\install.ps1   # Windows
./install.sh    # macOS / Linux
```

安裝腳本:

1. 建 `.venv` 並裝 Python 依賴(含 `edge-tts`)。
2. 寫一份預設 `.env`(若不存在)。
3. 把 `Stop` hook 註冊到 `~/.claude/settings.json`,直接呼叫 venv Python(不經過 shell wrapper,避免 stdin 編碼被改)。
4. 把 `/listen` 和 `/choose-voice` skill 裝到 `~/.claude/skills/`。
5. 若安裝時設了 `PIPER_VOICE` 環境變數,順便下載 Piper 模型。

冪等 — 隨時重跑都安全。

## 使用

### 控制 — `/listen` skill

一個 skill 同時管 開關 跟 朗讀詳細度。所有變更下一則 Claude 回應立即生效,不用重啟。

**開關:**

```
/listen           → 切換目前狀態
/listen on        → 開啟
/listen off       → 關閉
/listen status    → 查狀態
```

**朗讀模式**(每則回應怎麼被改寫成口語):

```
/listen llm       → 用 Claude 改寫成自然口語摘要(~$0.001 / 則)
/listen brief     → 只念開頭一段(啟發式)
/listen progress  → 開頭 + 前 ~4 個 bullet(預設,啟發式)
/listen summary   → 每段第一句 + 標題(啟發式)
/listen detailed  → 整則回應全念
/listen mode      → 印出目前模式
```

`/listen llm`(別名 `smart`)會呼叫本地 `claude -p`(預設 Haiku)把每則回應改寫成自然口語摘要 — 不會念出 markdown、code block、URL 等。會多 ~3–8 秒延遲;若 CLI 不存在或失敗會 fallback 到 `progress`。

等價腳本(skill 底下就是叫它):

```bash
.\scripts\toggle.ps1  <arg>   # Windows
bash scripts/toggle.sh <arg>  # macOS / Linux
```

開關用 marker 檔(`$TMPDIR/listen-claude.disabled`),模式寫進 `.env`。

### 挑聲音 — `/choose-voice` skill

```
/choose-voice                                 → 列選項
/choose-voice list edge Chinese voices        → 列 Edge 的中文聲音
/choose-voice use zh-TW-HsiaoChenNeural       → 換聲音
/choose-voice 我現在用哪個聲音
```

Skill 從 voice ID 格式自動判斷引擎(`zh-TW-…Neural` → Edge、`zh_CN-…` → Piper、20 字元 alphanumeric → ElevenLabs、其他 → system)。

#### 引擎一覽

| 引擎 | 費用 | 品質 | 設定 | 適用 |
|------|------|------|------|------|
| **`edge`**(預設) | 免費 | 高(神經網路) | 自動 | 不知道選哪個就用這個 |
| `system` | 免費 | 普通 | 無 | 不想連網、想最輕量 |
| `piper` | 免費 | 高(神經網路) | 手動下載模型 | 純離線 / 不出網路 |
| `elevenlabs` | 付費 | 頂級 | 需 API key | 對音質要求極高 |

**Edge TTS** — 熱門中文聲音:`zh-TW-HsiaoChenNeural`(TW 女,預設)、`zh-TW-YunJheNeural`(TW 男)、`zh-CN-XiaoxiaoNeural`(CN 女)、`yue-HK-WanLungNeural`(粵語)。完整清單:`.venv/bin/edge-tts --list-voices`。

**系統內建** — `Mei-Jia`(mac TW)、`Tingting`(mac CN)、`Microsoft Yating Desktop`(Win TW)。設 `TTS_ENGINE=system`。

**Piper** — 下載聲音再切換:

```bash
.\scripts\install-piper-voice.ps1 zh_CN-huayan-medium  ;  .\scripts\set-voice.ps1 zh_CN-huayan-medium piper   # Windows
bash scripts/install-piper-voice.sh zh_CN-huayan-medium && bash scripts/set-voice.sh zh_CN-huayan-medium piper  # macOS / Linux
```

試聽:<https://rhasspy.github.io/piper-samples/>。完整目錄:<https://huggingface.co/rhasspy/piper-voices/tree/main>。

**ElevenLabs** — 到 <https://elevenlabs.io/app/voice-library> 複製喜歡的 voice ID,然後:

```
TTS_ENGINE=elevenlabs
TTS_VOICE=<voice_id>
ELEVENLABS_API_KEY=<你的金鑰>
```

## 解除安裝

```bash
.\uninstall.ps1      # Windows
./uninstall.sh       # macOS / Linux
```

從 `~/.claude/settings.json` 移除 Stop hook。檔案保留。

---

## 設定(`.env`)

| 變數 | 預設 | 說明 |
|------|------|------|
| `TTS_ENABLED` | `1` | `0` 暫停 TTS(不用 uninstall) |
| `TTS_ENGINE` | `edge` | `edge` / `system` / `piper` / `elevenlabs` |
| `TTS_VOICE` | `zh-TW-HsiaoChenNeural` | 引擎對應的 voice ID |
| `TTS_MODE` | `progress` | `llm` / `progress` / `first` / `summary` / `full`;可用 `/listen <mode>` 即時切換 |
| `TTS_LLM_MODEL` | `claude-haiku-4-5` | `TTS_MODE=llm` 時 `claude -p` 呼叫的模型 |
| `TTS_LLM_TIMEOUT_SEC` | `60` | LLM 改寫超過此秒數就 fallback 到 `progress` |
| `TTS_MIN_WORDS` | `20` | 短於此字數的回應不念 |
| `TTS_MAX_CHARS` | `500` | 截斷過長回應 |
| `TTS_RATE` | `200` | 大略 wpm |
| `ANNOUNCE_PROJECT` | `1` | 在朗讀前先報專案 / 視窗名 |
| `PIPER_VOICES_DIR` | `~/.cache/piper-voices` | Piper 模型檔目錄 |

## 運作原理

```
Claude 回完話
        ↓ Stop hook 觸發
scripts/stop_hook_entry.py 從 stdin 收 JSON
        ↓
listen_bridge.runner:
  1. 從 payload 解出最後一則 assistant message
  2. 套用 TTS_MODE(llm / progress / brief / summary / full) — `llm` 模式
     會叫 `claude -p` 改寫成自然口語摘要
  3. 去掉 code block 跟 markdown 噪音
  4. 截斷到 TTS_MAX_CHARS
  5. 拿 per-host lock(若有其他視窗在播就排隊)
  6. 派給 TTS_ENGINE
        ↓
TTS 在背景播音 — 不會阻塞 Claude Code。
```

## 日誌

`%TEMP%\listen-claude.log`(Windows) 或 `$TMPDIR/listen-claude.log`(Unix)。

## 與其他 Claude Code plugin 共存

Listen-Claude 只加 `Stop` hook,跟用 `SessionStart` / `SessionEnd` / `PreToolUse` 等其他 hook 的 plugin 不衝突 — 包含 [Kaikou-Claude](https://github.com/GeniusPudding/Kaikou-Claude)(中文語音輸入)。`patch_settings.py` 用已知 substring 識別自己的 entry,重裝/解除不會誤砍別人的 hook。
