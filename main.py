from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import webbrowser

from tt.engine import MeetingEngine
from tt.hotkey import Hotkey
from tt.storage import (load_api_key, load_openai_api_key, load_settings, save_api_key,
                        save_openai_api_key, save_settings, transcript_dir, Transcript)
from tt.summary import answer_question, line_at, summarize
from tt.voices import VoiceProfiles


class TTApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TT Transcriber")
        self.root.geometry("1280x700")
        self.root.minsize(950, 440)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.events: queue.Queue = queue.Queue()
        self.hotkey = Hotkey(self.events)
        self.settings = load_settings()
        self.engine: MeetingEngine | None = None
        self.transcript: Transcript | None = None
        self.running = False
        self.had_error = False
        self.partials: dict[str, str] = {}
        self.last_live = ""
        self.timeline_selection: tuple[int, int] | None = None
        self.timeline_anchor: int | None = None
        self.summary_request_id = 0
        self.chat_request_id = 0
        self.current_summary = ""
        self.current_cycle_range = ""
        self.current_dialogue: list[dict] = []
        self.previous_dialogues: list[dict] = []
        self.chat_pending_question = ""
        self._build()
        self._install_hotkey()
        self.root.after(80, self._drain)

    def _build(self):
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Open transcript folder", command=self.open_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close)
        menu.add_cascade(label="File", menu=file_menu)
        menu.add_command(label="Options", command=self.open_options)
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label="AssemblyAI API Key", command=self.open_key)
        tools.add_command(label="OpenAI API Key (Summary & Chat)", command=self.open_openai_key)
        tools.add_separator()
        tools.add_command(label="Test AssemblyAI connection", command=self.test_connection)
        tools.add_command(label="Test OpenAI connection", command=self.test_openai_connection)
        menu.add_cascade(label="Tools", menu=tools)
        self.root.config(menu=menu)

        top = ttk.Frame(self.root, padding=14)
        top.pack(fill="x")
        ttk.Label(top, text="TT Transcriber", font=("Segoe UI", 18, "bold")).pack(side="left")
        self.action = ttk.Button(top, text="Start (Ctrl+Alt+Q)", command=self.toggle)
        self.action.pack(side="right")
        self.state_label = ttk.Label(self.root, text="Ready", padding=(14, 0))
        self.state_label.pack(fill="x")

        live_card = tk.Frame(self.root, bg="#17324d", padx=16, pady=12)
        live_card.pack(fill="x", padx=14, pady=(12, 0))
        self.live_heading = tk.Label(
            live_card, text="LIVE · CURRENT SPEECH", bg="#17324d", fg="#7ed9ff",
            font=("Segoe UI", 10, "bold"), anchor="w",
        )
        self.live_heading.pack(fill="x")
        self.live_label = tk.Label(
            live_card, text="Waiting for speech…", bg="#17324d", fg="white",
            font=("Segoe UI", 16, "bold"), anchor="w", justify="left",
            wraplength=820, pady=8,
        )
        self.live_label.pack(fill="x")
        live_card.bind("<Configure>", lambda event: self.live_label.config(wraplength=max(300, event.width - 32)))

        workspace = ttk.Frame(self.root, padding=(14, 12, 14, 8))
        workspace.pack(fill="both", expand=True)
        body = ttk.Frame(workspace)
        body.pack(side="left", fill="both", expand=True)
        self.text = tk.Text(body, wrap="word", font=("Consolas", 11), state="disabled")
        scrollbar = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.timeline = tk.Canvas(workspace, width=38, highlightthickness=0, bg="#e8eee9", cursor="crosshair")
        self.timeline.pack(side="left", fill="y", padx=(10, 8))
        self.timeline.bind("<Configure>", lambda _event: self._draw_timeline())
        self.timeline.bind("<ButtonPress-1>", self._timeline_press)
        self.timeline.bind("<B1-Motion>", self._timeline_drag)
        self.timeline.bind("<ButtonRelease-1>", self._timeline_release)

        summary_panel = ttk.Frame(workspace, width=360)
        summary_panel.pack(side="right", fill="y")
        summary_panel.pack_propagate(False)
        composer = ttk.Frame(summary_panel)
        composer.pack(side="bottom", fill="x", pady=(7, 0))
        self.send_question_button = ttk.Button(composer, text="Ask", command=self.ask_question)
        self.send_question_button.pack(side="right", padx=(6, 0))
        self.question_entry = tk.Text(composer, height=2, wrap="word", font=("Segoe UI", 10))
        self.question_entry.pack(side="left", fill="x", expand=True)
        self.question_entry.bind("<Return>", self._question_enter)

        self.detail_panes = tk.PanedWindow(
            summary_panel, orient=tk.VERTICAL, sashwidth=10, showhandle=True,
            handlesize=18, handlepad=12, opaqueresize=True, bg="#d5dde5", bd=0,
        )
        self.detail_panes.pack(fill="both", expand=True)

        summary_section = ttk.Frame(self.detail_panes)
        ttk.Label(summary_section, text="AI summary & chat", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        self.summary_range = ttk.Label(summary_section, text="Drag on the green bar to select a section.",
                                       wraplength=340, foreground="#476477")
        self.summary_range.pack(fill="x", pady=(5, 10))
        summary_body = ttk.Frame(summary_section)
        summary_body.pack(fill="both", expand=True)
        self.summary_text = tk.Text(summary_body, wrap="word", font=("Segoe UI", 11),
                                    state="disabled", bg="#f5f9fb", relief="flat", padx=12, pady=12)
        summary_scroll = ttk.Scrollbar(summary_body, command=self.summary_text.yview)
        self.summary_text.configure(yscrollcommand=summary_scroll.set)
        self.summary_text.pack(side="left", fill="both", expand=True)
        summary_scroll.pack(side="right", fill="y")
        self._set_summary("Select part of the transcript to summarize it in Italian.")

        chat_section = ttk.Frame(self.detail_panes)
        ttk.Label(chat_section, text="Questions about the whole meeting",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 6))
        chat_body = ttk.Frame(chat_section)
        chat_body.pack(fill="both", expand=True)
        self.chat_text = tk.Text(chat_body, wrap="word", font=("Segoe UI", 10),
                                 state="disabled", bg="#f5f9fb", relief="flat", padx=10, pady=10)
        chat_scroll = ttk.Scrollbar(chat_body, command=self.chat_text.yview)
        self.chat_text.configure(yscrollcommand=chat_scroll.set)
        self.chat_text.pack(side="left", fill="both", expand=True)
        chat_scroll.pack(side="right", fill="y")
        self.detail_panes.add(summary_section, minsize=95, height=180)
        self.detail_panes.add(chat_section, minsize=95)
        self._set_question_enabled(False)
        self._render_chat()
        self.path_label = ttk.Label(self.root, text="No session yet", padding=(14, 6))
        self.path_label.pack(fill="x")
        self._show_live()

    def _show_live(self):
        if self.partials:
            self.live_heading.config(text="LIVE · CURRENT SPEECH")
            self.live_label.config(text="\n".join(list(self.partials.values())[-2:]))
        elif self.last_live:
            self.live_heading.config(text="LAST CONFIRMED")
            self.live_label.config(text=self.last_live)
        else:
            self.live_heading.config(text="LIVE · CURRENT SPEECH" if self.running else "READY")
            self.live_label.config(text="Waiting for speech…" if self.running else "Press Start to transcribe")

    def _set_summary(self, text: str):
        self.summary_text.config(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", text)
        self.summary_text.config(state="disabled")

    def _set_question_enabled(self, enabled: bool):
        self.question_entry.config(state="normal" if enabled else "disabled")
        self.send_question_button.config(state="normal" if enabled else "disabled")

    def _render_chat(self):
        self.chat_text.config(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.tag_configure("who", font=("Segoe UI", 10, "bold"), foreground="#17324d")
        if not self.current_dialogue and not self.chat_pending_question:
            self.chat_text.insert("end", "Ask about any part of the transcript, including outside the yellow section.")
        for turn in self.current_dialogue:
            self.chat_text.insert("end", "You\n", "who")
            self.chat_text.insert("end", f"{turn['question']}\n\n")
            self.chat_text.insert("end", "AI\n", "who")
            self.chat_text.insert("end", f"{turn['answer']}\n\n")
        if self.chat_pending_question:
            self.chat_text.insert("end", "You\n", "who")
            self.chat_text.insert("end", f"{self.chat_pending_question}\n\n")
            self.chat_text.insert("end", "AI\n", "who")
            self.chat_text.insert("end", "Thinking…")
        self.chat_text.see("end")
        self.chat_text.config(state="disabled")

    def _question_enter(self, event):
        if event.state & 0x0001:  # Shift+Enter inserts a new line.
            return None
        self.ask_question()
        return "break"

    def ask_question(self):
        if not self.transcript or self.chat_pending_question:
            return
        question = self.question_entry.get("1.0", "end").strip()
        if not question:
            return
        try:
            key = load_openai_api_key().strip()
        except Exception as exc:
            self._set_summary(f"Cannot read the OpenAI key: {exc}")
            return
        if not key:
            self._set_summary("Add your OpenAI API key in Tools → OpenAI API Key (Summary & Chat).")
            return
        lines = [self.transcript.format_line(item) for item in self._speech_items()]
        if not lines:
            return
        self.chat_request_id += 1
        request_id = self.chat_request_id
        self.chat_pending_question = question
        self.question_entry.delete("1.0", "end")
        self._set_question_enabled(False)
        self._render_chat()
        current_summary = self.current_summary
        current_dialogue = deepcopy(self.current_dialogue)
        previous_dialogues = deepcopy(self.previous_dialogues)
        def worker():
            try:
                answer = answer_question(key, lines, question, current_summary,
                                         current_dialogue, previous_dialogues)
                self.events.put(("chat_ok", (request_id, question, answer)))
            except Exception as exc:
                self.events.put(("chat_error", (request_id, question, str(exc))))
        threading.Thread(target=worker, daemon=True, name="TT-chat").start()

    def _begin_new_chat_cycle(self):
        if self.current_summary or self.current_dialogue:
            self.previous_dialogues.append({
                "selection": self.current_cycle_range,
                "summary": self.current_summary,
                "questions_and_answers": deepcopy(self.current_dialogue),
            })
        self.chat_request_id += 1
        self.current_summary = ""
        self.current_cycle_range = ""
        self.current_dialogue = []
        self.chat_pending_question = ""
        self.question_entry.config(state="normal")
        self.question_entry.delete("1.0", "end")
        self._set_question_enabled(False)
        self._render_chat()

    def _speech_items(self) -> list[dict]:
        return [item for item in self.transcript.lines if item["speaker"] != "SYSTEM"] if self.transcript else []

    def _timeline_weights(self, items: list[dict]) -> list[int]:
        return [max(1, len(self.transcript.format_line(item))) for item in items]

    def _draw_timeline(self):
        width = max(1, self.timeline.winfo_width())
        height = max(1, self.timeline.winfo_height())
        self.timeline.delete("all")
        self.timeline.create_rectangle(4, 0, width - 4, height, fill="#2ca75b", outline="")
        items = self._speech_items()
        count = len(items)
        if self.timeline_selection and count:
            first, last = self.timeline_selection
            weights = self._timeline_weights(items)
            total = sum(weights)
            top = height * sum(weights[:first]) / total
            bottom = max(top + 2, height * sum(weights[:last + 1]) / total)
            self.timeline.create_rectangle(4, top, width - 4, bottom, fill="#ffd443", outline="#d6a100")

    def _timeline_position(self, y: int) -> int | None:
        items = self._speech_items()
        return line_at(y, self.timeline.winfo_height(), self._timeline_weights(items)) if items else None

    def _show_selection_range(self, dragging: bool):
        if not self.timeline_selection:
            return
        items = self._speech_items()
        first, last = self.timeline_selection
        if last >= len(items):
            return
        start = datetime.fromisoformat(items[first]["when"]).strftime("%H:%M:%S")
        end = datetime.fromisoformat(items[last]["when"]).strftime("%H:%M:%S")
        suffix = " · Release to summarize" if dragging else ""
        self.summary_range.config(text=f"{start}–{end} · Lines {first + 1}–{last + 1} of {len(items)}{suffix}")

    def _timeline_press(self, event):
        index = self._timeline_position(event.y)
        if index is None:
            self.summary_range.config(text="Start transcribing to select a section.")
            return
        self.timeline_anchor = index
        self.timeline_selection = (index, index)
        self.summary_request_id += 1
        self._set_summary("Release the mouse to summarize the yellow section.")
        self._draw_timeline()
        self._show_selection_range(dragging=True)

    def _timeline_drag(self, event):
        if self.timeline_anchor is None:
            return
        index = self._timeline_position(event.y)
        if index is None:
            return
        self.timeline_selection = (min(self.timeline_anchor, index), max(self.timeline_anchor, index))
        self._draw_timeline()
        self._show_selection_range(dragging=True)

    def _timeline_release(self, event):
        if self.timeline_anchor is None:
            return
        self._timeline_drag(event)
        self.timeline_anchor = None
        self._show_selection_range(dragging=False)
        self._begin_new_chat_cycle()
        self._request_summary()

    def _request_summary(self):
        if not self.timeline_selection or not self.transcript:
            return
        try:
            key = load_openai_api_key().strip()
        except Exception as exc:
            self._set_summary(f"Cannot read the OpenAI key: {exc}")
            return
        if not key:
            self._set_summary("Add your OpenAI API key in Tools → OpenAI API Key (Summary & Chat).")
            return
        items = self._speech_items()
        first, last = self.timeline_selection
        if not items or last >= len(items):
            return
        lines = [self.transcript.format_line(item) for item in items]
        self.current_cycle_range = self.summary_range.cget("text")
        self.summary_request_id += 1
        request_id = self.summary_request_id
        self._set_summary("Summarizing the selected section…")
        def worker():
            try:
                result = summarize(key, lines, first, last)
                self.events.put(("summary_ok", (request_id, result)))
            except Exception as exc:
                self.events.put(("summary_error", (request_id, str(exc))))
        threading.Thread(target=worker, daemon=True, name="TT-summary").start()

    def _install_hotkey(self):
        shortcut = self.settings.get("hotkey", "Ctrl+Alt+Q")
        try:
            self.hotkey.start(shortcut)
            self.action.config(text=f"Start ({shortcut})")
        except (ValueError, RuntimeError) as exc:
            messagebox.showwarning("Shortcut unavailable", str(exc))

    def open_folder(self):
        import os
        os.startfile(transcript_dir())

    def open_key(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("AssemblyAI API Key")
        dialog.geometry("540x150")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Paste your AssemblyAI API key:", padding=12).pack(anchor="w")
        value = tk.StringVar(value=load_api_key())
        entry = ttk.Entry(dialog, textvariable=value, show="*", width=65)
        entry.pack(fill="x", padx=12)
        entry.focus_set()
        def save():
            save_api_key(value.get())
            dialog.destroy()
        ttk.Button(dialog, text="Save", command=save).pack(anchor="e", padx=12, pady=12)

    def open_openai_key(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("OpenAI API Key")
        dialog.geometry("540x170")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Paste your OpenAI API key for summaries and chat:", padding=12).pack(anchor="w")
        value = tk.StringVar(value=load_openai_api_key())
        entry = ttk.Entry(dialog, textvariable=value, show="*", width=65)
        entry.pack(fill="x", padx=12)
        entry.focus_set()
        def save():
            try:
                save_openai_api_key(value.get())
            except Exception as exc:
                messagebox.showerror("OpenAI API Key", str(exc), parent=dialog)
                return
            dialog.destroy()
            if self.timeline_selection:
                self._request_summary()
        ttk.Button(dialog, text="Save", command=save).pack(anchor="e", padx=12, pady=12)

    def test_connection(self):
        key = load_api_key().strip()
        if not key:
            messagebox.showwarning("AssemblyAI", "Enter your API key in Tools first.")
            return
        def worker():
            import asyncio
            import websockets
            try:
                async def check():
                    async with websockets.connect(
                        "wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&speech_model=universal-3-6-pro",
                        additional_headers={"Authorization": key}, open_timeout=10) as socket:
                        import json
                        response = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
                        if response.get("type") != "Begin":
                            raise RuntimeError(f"Unexpected AssemblyAI response: {response.get('type')}")
                        await socket.send('{"type":"Terminate"}')
                        await asyncio.wait_for(socket.recv(), timeout=10)
                asyncio.run(check())
                self.events.put(("test_ok", None))
            except Exception as exc:
                self.events.put(("test_error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def test_openai_connection(self):
        try:
            key = load_openai_api_key().strip()
        except Exception as exc:
            messagebox.showerror("OpenAI", f"Cannot read the OpenAI key: {exc}")
            return
        if not key:
            messagebox.showwarning("OpenAI", "Enter your OpenAI API key in Tools first.")
            return
        def worker():
            try:
                # Use the same model and endpoint as a real summary, with a
                # tiny sample. Authentication alone would not test model access.
                summarize(key, ["[00:00:00] Person1: Hello."], 0, 0)
                self.events.put(("openai_test_ok", None))
            except Exception as exc:
                self.events.put(("openai_test_error", str(exc)))
        threading.Thread(target=worker, daemon=True, name="TT-OpenAI-test").start()

    def open_options(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Options")
        dialog.geometry("560x420")
        dialog.transient(self.root)
        ttk.Label(dialog, text="Shortcut", padding=(12, 12, 12, 2)).pack(anchor="w")
        shortcut = tk.StringVar(value=self.settings.get("hotkey", "Ctrl+Alt+Q"))
        row = ttk.Frame(dialog, padding=(12, 0))
        row.pack(fill="x")
        ttk.Entry(row, textvariable=shortcut, width=22).pack(side="left")
        def save_shortcut():
            old = self.settings.get("hotkey", "Ctrl+Alt+Q")
            try:
                self.hotkey.start(shortcut.get())
            except (ValueError, RuntimeError) as exc:
                self.hotkey.start(old)
                messagebox.showwarning("Shortcut unavailable", str(exc), parent=dialog)
                return
            self.settings = load_settings()
            self.settings["hotkey"] = shortcut.get()
            save_settings(self.settings)
            self.action.config(text=("Stop" if self.running else "Start") + f" ({shortcut.get()})")
        ttk.Button(row, text="Apply", command=save_shortcut).pack(side="left", padx=8)

        ttk.Label(dialog, text="Speakers in current session", padding=(12, 18, 12, 2)).pack(anchor="w")
        speakers = tk.Listbox(dialog, height=10)
        speakers.pack(fill="both", expand=True, padx=12)
        def refresh():
            speakers.delete(0, "end")
            if self.transcript:
                for speaker, number in self.transcript.speaker_numbers.items():
                    if speaker != "SYSTEM":
                        generic = f"Person{number}"
                        speakers.insert("end", f"{generic}  →  {self.transcript.label(speaker)}")
        refresh()
        def assign():
            selected = speakers.curselection()
            if not selected or not self.transcript:
                return
            speaker = list(k for k in self.transcript.speaker_numbers if k != "SYSTEM")[selected[0]]
            name = simpledialog.askstring("Name speaker", "Name for this speaker:", parent=dialog)
            if name and name.strip():
                if self.engine:
                    self.engine.assign_name(speaker, name.strip())
                else:
                    self.transcript.rename(speaker, name.strip())
                    self._render()
                refresh()
        ttk.Button(dialog, text="Assign name", command=assign).pack(anchor="e", padx=12, pady=10)
        profile_row = ttk.Frame(dialog, padding=(12, 4))
        profile_row.pack(fill="x")
        ttk.Label(profile_row, text="Saved voice profiles:").pack(side="left")
        profiles = VoiceProfiles()
        profile_choices = [f"{profile['name']}  ({profile_id[:8]})" for profile_id, profile in profiles.profiles.items()]
        profile_ids = list(profiles.profiles)
        profile_choice = tk.StringVar(value=profile_choices[0] if profile_choices else "No profiles yet")
        ttk.OptionMenu(profile_row, profile_choice, profile_choice.get(), *profile_choices).pack(side="left", padx=8)
        def delete_profile():
            if profile_choice.get() not in profile_choices:
                return
            profile_id = profile_ids[profile_choices.index(profile_choice.get())]
            profiles.delete(profile_id)
            messagebox.showinfo("Profile deleted", "Old transcripts keep their names. Future meetings will not use this profile.", parent=dialog)
            dialog.destroy()
        ttk.Button(profile_row, text="Delete", command=delete_profile).pack(side="right")

    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        key = load_api_key().strip()
        if not key:
            messagebox.showwarning("AssemblyAI key needed", "Enter your AssemblyAI API key in Tools → AssemblyAI API Key.")
            return
        try:
            self.transcript = Transcript()
        except OSError as exc:
            messagebox.showerror("Cannot create transcript", str(exc))
            return
        self.engine = MeetingEngine(key, self.transcript, lambda kind, data: self.events.put((kind, data)))
        self.running = True
        self.had_error = False
        self.partials.clear()
        self.last_live = ""
        self.timeline_selection = None
        self.timeline_anchor = None
        self.summary_request_id += 1
        self.chat_request_id += 1
        self.current_summary = ""
        self.current_cycle_range = ""
        self.current_dialogue = []
        self.previous_dialogues = []
        self.chat_pending_question = ""
        self.question_entry.config(state="normal")
        self.question_entry.delete("1.0", "end")
        self._set_question_enabled(False)
        self._render_chat()
        self.summary_range.config(text="Drag on the green bar to select a section.")
        self._set_summary("Select part of the transcript to summarize it in Italian.")
        self._show_live()
        self._render()
        self.path_label.config(text=str(self.transcript.path))
        self.state_label.config(text="Connecting and recording…")
        self.action.config(text=f"Stop ({self.settings.get('hotkey', 'Ctrl+Alt+Q')})")
        self.root.deiconify()
        self.root.lift()
        self.engine.start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.state_label.config(text="Stopping and saving…")
        self.action.config(state="disabled")
        engine = self.engine
        threading.Thread(target=engine.stop, daemon=True).start()

    def close(self):
        if self.running:
            if not messagebox.askyesno("Stop transcription?", "Stop transcription, save the TXT file and close TT?"):
                return
            self.stop()
            self.root.after(100, self._close_when_stopped)
        else:
            self.hotkey.stop()
            self.root.destroy()

    def _close_when_stopped(self):
        if self.engine and self.engine.thread and self.engine.thread.is_alive():
            self.root.after(100, self._close_when_stopped)
        else:
            self.hotkey.stop()
            self.root.destroy()

    def _render(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        if self.transcript:
            self.text.insert("end", "\n".join(self.transcript.format_line(item) for item in self.transcript.lines))
        self.text.see("end")
        self.text.config(state="disabled")
        self._draw_timeline()

    def _drain(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "hotkey":
                    self.toggle()
                elif kind == "status":
                    self.state_label.config(text=data)
                elif kind == "partial":
                    if self.transcript:
                        speaker = data["speaker"]
                        # AssemblyAI may send UNKNOWN on early partials, then
                        # identify the speaker on the final turn. Do not spend
                        # a permanent Person number on that provisional label.
                        label = "Person?" if speaker.endswith(":UNKNOWN") else self.transcript.label(speaker)
                        self.partials.pop(speaker, None)
                        self.partials[speaker] = f"{label}: {data['text']}"
                        self._show_live()
                elif kind == "final":
                    self.partials.pop(data["speaker"], None)
                    if data["speaker"].startswith("remote:"):
                        self.partials.pop(data["speaker"].rsplit(":", 1)[0] + ":UNKNOWN", None)
                    if self.transcript:
                        self.last_live = f"{self.transcript.label(data['speaker'])}: {data['text']}"
                    self._show_live()
                    self._render()
                elif kind == "refresh":
                    if self.transcript and self.transcript.lines:
                        latest = self.transcript.lines[-1]
                        if latest["speaker"] != "SYSTEM":
                            self.last_live = f"{self.transcript.label(latest['speaker'])}: {latest['text']}"
                    self._show_live()
                    self._render()
                elif kind == "stopped":
                    self.running = False
                    self.state_label.config(text="Stopped after error; transcript saved" if self.had_error else "Saved")
                    self.action.config(state="normal", text=f"Start ({self.settings.get('hotkey', 'Ctrl+Alt+Q')})")
                    self.partials.clear()
                    self._show_live()
                    self._render()
                elif kind == "error":
                    self.had_error = True
                    self.state_label.config(text=f"Error: {data}")
                elif kind == "test_ok":
                    messagebox.showinfo("AssemblyAI", "Connection successful.")
                elif kind == "test_error":
                    messagebox.showerror("AssemblyAI", f"Connection failed: {data}")
                elif kind == "openai_test_ok":
                    messagebox.showinfo("OpenAI", "Connection successful. Summaries are available.")
                elif kind == "openai_test_error":
                    messagebox.showerror("OpenAI", f"Connection failed: {data}")
                elif kind == "summary_ok":
                    request_id, result = data
                    if request_id == self.summary_request_id:
                        self.current_summary = result
                        self._set_summary(result)
                        self._set_question_enabled(True)
                elif kind == "summary_error":
                    request_id, error = data
                    if request_id == self.summary_request_id:
                        self._set_summary(f"Summary unavailable: {error}")
                        self._set_question_enabled(bool(self.timeline_selection))
                elif kind == "chat_ok":
                    request_id, question, answer = data
                    if request_id == self.chat_request_id:
                        self.current_dialogue.append({"question": question, "answer": answer})
                        self.chat_pending_question = ""
                        self._set_question_enabled(True)
                        self._render_chat()
                elif kind == "chat_error":
                    request_id, question, error = data
                    if request_id == self.chat_request_id:
                        self.chat_pending_question = ""
                        self._set_question_enabled(True)
                        self._render_chat()
                        self.chat_text.config(state="normal")
                        self.chat_text.insert("end", f"\nCould not answer ‘{question}’: {error}")
                        self.chat_text.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    TTApp().run()
