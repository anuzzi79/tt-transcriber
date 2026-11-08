# TT — Windows meeting transcriber

## Goal

A small Windows 11 desktop app that transcribes English software meetings live without joining the Teams meeting. It captures the current default Windows output device and the current default microphone. The microphone is always labeled Antonio. The app uses AssemblyAI for live transcription and speaker diarization.

## Agreed behavior

- The user starts the app manually from the desktop icon or Start menu. Automatic start with Windows is deferred.
- The app then remains ready in the background. `Ctrl+Alt+Q` starts a session, opens the normal window, and a second press stops the session. The shortcut is configurable; registration conflicts are reported.
- The window shows the live transcript. Partial phrases may change; final phrases are written to a UTF-8 `.txt` file progressively. Stopping leaves the window open and the file saved.
- Files go in the user's Windows Documents folder under `3transcript`, with names such as `TT_2026-11-08_10-30.txt`.
- Each final line has a local timestamp, speaker name, and text: `[10:42:15] Eric: We can review it tomorrow.`
- Remote speakers initially appear as `Person1`, `Person2`, and so on. Uncertain or too-short speech stays generic rather than being forced to a known name.
- In Options, the user can map a session speaker to a real name. The app stores a local voice profile for later sessions and applies a confident match immediately. Correcting a name updates associated lines in existing transcript files. Deleting a profile stops future recognition but preserves names already written in old files.
- Tools contains an AssemblyAI API key field. The key is stored using Windows-protected storage. Key problems are shown only when the user starts transcription. Tools also offers a connection test.
- Both audio sources follow changes to the Windows default device while recording. A minimized window keeps recording.
- Closing the window during transcription asks for confirmation; confirming stops, flushes the transcript, and exits.
- On a connection failure, the window shows reconnection status and retries immediately. A five-minute in-memory audio buffer allows catch-up; any unrecoverable interval is marked in the text. No meeting audio is kept as a file.
- The interface is in English. The first test uses user-selected YouTube video calls, then playback plus Antonio speaking into the microphone.

## Implementation stages

1. **Desktop shell and settings.** Build a Windows installer with desktop and Start shortcuts, a tray-ready process, the configurable global shortcut, main window, Options, and Tools. Verify that pressing the shortcut starts and stops exactly one session.
2. **Audio capture.** Capture the default render endpoint through Windows loopback and the default capture endpoint for the microphone. Detect endpoint changes and reattach without duplicating speech. Verify with speakers, headphones, and a microphone switch.
3. **Live transcription and persistence.** Start with separate AssemblyAI streaming sessions for output and microphone, enabling diarization on the output stream. Merge finalized turns by timestamp, label the microphone Antonio, and append transcript lines progressively. Use the model's built-in conversation context and an initial software-meeting prompt. Because context is held per stream, test whether this separation loses important context from the other side of the conversation; compare a mixed-audio prototype before fixing the final routing. Handle partial text, startup errors, stop, and unexpected exit.
4. **Voice profiles.** Prototype local speaker embeddings from sufficiently long, clean remote speech. Measure repeat-session matching on the selected test videos. Set a conservative match threshold and leave uncertain voices as `PersonN`. Add rename, correction of associated historical transcripts, and profile deletion. This stage requires validation because AssemblyAI does not provide native cross-session voice registration.
5. **Recovery and packaging.** Add reconnection, the bounded memory buffer, gap markers, key protection, installer, desktop/Start entries, and acceptance tests on Windows 11.

## Acceptance checks

- `Ctrl+Alt+Q` starts transcription from the ready app and stops it; stopping leaves the transcript visible.
- Output and microphone speech both appear, and microphone speech is attributed to Antonio.
- Switching the default output or microphone during a session resumes capture from the new device.
- A `.txt` file appears at session start and grows as finalized phrases arrive; closing with X prompts and saves.
- At least two remote voices in a representative English software conversation receive distinct generic labels when the audio permits it.
- Assigning a real name updates the current and related old transcripts; a confident repeat-session voice uses that name, while an uncertain one stays generic.
- Deleting a profile does not change already saved names.
- A temporary AssemblyAI interruption causes immediate retry, recovery from the memory buffer where possible, and a visible gap marker if audio is lost.

## Known constraints and cost

Speaker diarization in live audio can be wrong on short replies and overlapping speech. Context can help resolve plausible words but cannot reliably recover speech that was not captured. Persistent identification is a separate local component and must be measured before promising a reliable match. Output audio from Windows is not inherently linked to Teams participant names. OpenAI is not required for the initial transcription design.

AssemblyAI recommends one streaming session per audio channel. At current published pay-as-you-go rates, Universal-3.6 Pro Realtime is $0.45 per streaming hour and diarization is another $0.12 per hour. Two simultaneous one-hour streams, with diarization only on output, would be approximately $1.02 before any optional paid features. Confirm the model and live pricing before implementation and billing tests.

## Selected-section summaries

The window includes a vertical timeline next to the transcript. Its fixed height represents all finalized speech in the current session, weighted by the amount of transcript text. Dragging marks a contiguous section yellow; releasing immediately requests an Italian summary in the panel on the right. The request contains the selected lines as the summary target and the entire finalized transcript at that moment as context. Each new drag replaces the visible selection and invalidates older pending results. The OpenAI key is entered under Tools and stored separately using Windows DPAPI. Summaries stay in the UI and do not alter the TXT transcript.

The summary panel also contains a chat. Each question receives the entire finalized transcript available when the question is asked, the current summary, the current chat, and completed dialogues from earlier selections in the same transcription session. A new selection clears the visible chat and archives its completed exchanges in memory for future questions. Starting a new transcription session clears that in-memory dialogue history.

Sources: [AssemblyAI pricing](https://www.assemblyai.com/pricing/), [streaming diarization and multichannel](https://www.assemblyai.com/docs/universal-streaming/multichannel-streams), [cross-file identification limitation](https://support.assemblyai.com/articles/4595780683-do-you-offer-cross-file-speaker-identification), [Windows default-device events](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-immnotificationclient-ondefaultdevicechanged).
