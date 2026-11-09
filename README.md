# TT Transcriber

Windows 11 desktop meeting transcription using AssemblyAI. Start `main.py` with Python 3.11 or run `install-shortcuts.ps1` to create Desktop and Start menu shortcuts on this PC. The shortcut installer does not start the app with Windows.

For a workspace-only trial, double-click **Launch TT Test.vbs**. It stores its protected key and transcripts inside this project rather than in the final locations.

## Run

```powershell
python -m pip install -r requirements.txt
python main.py
```

In **Tools → AssemblyAI API Key**, paste the key and save it. It is protected with Windows DPAPI under the current user account. Press **Ctrl+Alt+Q** to start and stop. The transcript is written progressively to `Documents\3transcript\TT_<date>_<time>.txt`. The microphone is labeled **Antonio**. The window stays open when the shortcut stops a session.

While transcription is running, thin red borders around each connected display pulse with a 0.33-second fade cycle. The borders let mouse clicks through and disappear when recording stops.

To summarize a completed part of the current meeting, enter an OpenAI key under **Tools → OpenAI API Key (Summary & Chat)**. Drag along the vertical green timeline between the transcript and the summary panel. The selected section turns yellow; releasing the mouse starts an Italian summary in the right panel. A new drag replaces the selection and summary. The complete transcript at the time of release is sent to OpenAI as context, while the summary is instructed to cover only the selected lines. Each release starts a separate API request. Summaries are displayed in the app and are not added to the TXT file. The OpenAI key is stored separately with Windows DPAPI.

Below the summary, type a question and press Enter or **Ask**. Each question sends the entire finalized transcript as it exists **at that moment**, so answers can use speech before or after the yellow section, including lines added since the summary. The current summary and earlier questions and answers from this app session are included to resolve conversational references. Selecting a new yellow section clears the visible chat and starts a new one, while earlier completed dialogues remain in memory as context until a new transcription session starts. Questions and answers are not written to the TXT file. Each question is another OpenAI API request.

Drag the handle between **AI summary & chat** and **Questions about the whole meeting** up or down to give either pane more vertical space. The question entry stays at the bottom.

Once enough speech has been finalized, blue triangles appear just left of the green timeline. Hover over one to see the topic and its start time. Click one to select and summarize from that topic boundary to the next. Clicking the last triangle selects only through the latest finalized line at the time of the click; later speech does not expand the yellow selection or regenerate its summary. Dragging on the green bar still selects any interval. The app checks for new text every 20 seconds, updates recent topic boundaries when enough speech has arrived, and revisits the whole meeting about every five minutes and when transcription stops. Topic markers can move or merge; an existing yellow selection stays fixed. Markers are not written to the TXT.

Under **Options**, choose the OpenAI model for summaries, questions, topic markers, and the OpenAI connection test. `gpt-6-luna` is the default; `gpt-4o` is available as a temporary comparison option. GPT-4o is scheduled for API retirement on 14 January 2027. The model choice is saved locally. If GPT-4o becomes unavailable, the app reports this rather than switching models silently.

**Tools → Test AssemblyAI connection** checks only the AssemblyAI key. **Tools → Test OpenAI connection** sends a tiny summary request through the selected OpenAI model and endpoint used by the summary panel; it checks the OpenAI key and model access. The OpenAI test is an API request and may consume a small amount of credit.

## Current status

The app shell, two-source capture, AssemblyAI streaming connections, live text, progressive TXT writing, device-change detection, reconnection, shortcut, and manual name mapping are implemented. A live Windows loopback test with a YouTube video call now produces partial text in the window and finalized English turns in the TXT using Universal-3.6 Pro. The following parts still need validation before relying on this app for real meetings:

- Cross-meeting voice recognition uses a small local acoustic-profile prototype. It is conservative and has not been validated on representative speech; it may leave people as `PersonN` or make wrong matches. Do not treat automatic names as reliable until the planned video-call tests have measured them.
- Output diarization across several voices and microphone transcription as **Antonio** passed a live video-call test. Automatic voice matching in a later session and device switching have not yet passed a live test.
- The summary, chat, and topic timeline request handling passed local tests. Topic markers still need a live OpenAI test during a representative meeting.
- A progressive audio delay was traced to adding send overhead to every 200 ms packet. Wall-clock pacing now keeps the capture-to-send queue near 0.8–0.9 seconds in a live test lasting over two minutes; finalized turns can still wait for a speaker pause.
- Desktop and Start shortcuts are created only after running `install-shortcuts.ps1` on the PC. This workspace cannot write outside its project directory.
- Separate microphone and output streams do not share the full conversation context. Compare this routing with a mixed stream using representative calls before selecting the final design.

No meeting audio is written to disk. Settings and transcript metadata are stored in `%LOCALAPPDATA%\TTTranscriber`; the transcript itself is in Documents. `TT_DATA_DIR` and `TT_TRANSCRIPT_DIR` can override those paths for local tests.
