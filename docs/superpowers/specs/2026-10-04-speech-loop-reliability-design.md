# Speech Loop Reliability Design

Date: 2026-10-04

## Context and evidence

The desktop prototype connects an Electron renderer to a FastAPI backend. The backend sends agent replies to GPT-SoVITS and returns audio resources; the renderer captures one microphone recording and uploads it to `/asr` before sending the transcript through the same conversation channel.

The current implementation and local observations show:

- Ollama uses `qwen3:8b`. The Murasame system prompt asks for Chinese replies, but a prior integration transcript contained a Japanese reply.
- The WebSocket TTS path always sets `text_language="zh"`, while its reference prompt is Japanese: `murasame_ref.ogg`, with prompt text `はっはっはっは` and `prompt_language="ja"`.
- The only reference audio found under the project’s mounted reference directory is `murasame_ref.ogg`. Project documentation identifies it as a laugh and says it is not ideal for formal inference. The documented training-audio source directory is absent on this machine, so this change cannot select a replacement dialogue sample.
- `AudioRecorder.start()` waits for `getUserMedia()` before the UI changes the button to its recording state. While permission is pending, the UI still appears idle and allows another click. Startup and recorder-error paths do not consistently stop acquired media tracks or clear recorder state.
- The recent backend log contained health checks but no `/asr` request. This locates the last observed recording failure before the upload boundary; it does not identify whether the user’s microphone permission, selected device, or another runtime condition caused it.
- The local backend health endpoint, Ollama model listing, and GPT-SoVITS container were available during inspection. Existing output files are valid WAV containers, but no listening-based quality assessment was made.

## Goal

Make the existing single-recording speech conversation clearer and more reliable at the two observed boundaries: TTS language metadata and microphone recording lifecycle. Keep the established Murasame voice and character behavior.

## Proposed design

### TTS language selection

Keep the Murasame system prompt’s intended Chinese response behavior. Before synthesis, select the GPT-SoVITS `text_language` from the actual reply text: Japanese kana in the reply selects `ja`; otherwise select `zh`. Keep the current Japanese reference audio, its matching prompt text, and `prompt_language="ja"` unchanged. This keeps the actual target text language from being mislabeled while preserving the currently available voice assets.

The language rule is deliberately limited to Chinese and Japanese, the languages established by the current prompt and TTS configuration. It does not add a language-detection dependency or claim to handle arbitrary multilingual replies.

### Recording lifecycle

Give the recording control explicit idle, microphone-request, recording, and transcription states. Enter the microphone-request state before awaiting `getUserMedia()` and prevent repeat clicks while a start or upload operation is active. On success, switch to recording; on stop, switch to transcription; on failure, return to idle and display the concrete error.

Make `AudioRecorder` release every acquired media track and clear its recorder/stream references when startup, recording, or stop fails, as well as after a normal stop. Preserve the existing single-recording flow and `/asr` request contract.

### Documentation

Update the README’s current-state section to describe the language alignment behavior, recording states, and the remaining manual checks. Keep the laugh-reference limitation explicit until suitable source audio is available and selected.

## Scope boundaries

- Keep Ollama, the Murasame GPT and SoVITS weights, the Murasame persona, the current reference audio, ASR model selection, and the Mao Live2D verification asset unchanged.
- Do not add VAD, streaming recognition, device selection, new language dependencies, or replacement voice data.
- Do not claim that the real microphone or subjective speech quality is verified based on synthetic audio or service health alone.

## Error handling and observable behavior

- A pending microphone permission request is visible as a distinct in-progress state and cannot launch a second request through repeated clicks.
- A rejected microphone request or recorder error returns the control to idle, releases acquired tracks, and displays the error surfaced by the browser/Electron API.
- The ASR upload and conversation flow retain their existing endpoints and message protocol.
- The language selected for TTS follows the reply text under the Chinese/Japanese rule above.

## Verification and acceptance

- Run the desktop type check and build after implementation.
- Confirm the selected TTS language for Chinese replies and replies containing Japanese kana, and confirm the reference-audio request fields remain unchanged.
- Inspect the recording state transitions and cleanup paths for success, permission rejection, and recorder failure.
- Re-check the README against the implemented behavior.
- Report real microphone capture and listening-based voice quality as pending unless those paths are exercised in the Electron window with the user’s actual microphone and audio output.

## Risks

- Script-based selection supports only the two languages documented here; text containing Japanese kana inside an otherwise Chinese reply will select Japanese.
- The laugh reference remains a known quality limitation. Replacing it requires a suitable, available, and correctly transcribed Murasame dialogue recording.
- Static checks cannot prove Windows microphone permission, selected input-device quality, speaker playback, or perceived voice quality.
