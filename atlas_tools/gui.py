"""
The Tkinter window.

Three tabs over one shared log pane:

    Run       pick a tool, fill in its arguments, watch it run, answer prompts
    Deploy    push the Python and Node trees to the server over SFTP
    Settings  connection details and the file mappings, saved to deploy.json

Everything that blocks -- a task, a deploy -- happens off the Tk thread and
reports back through a queue that ``_drain`` empties on a timer. Only one
operation runs at a time, so the log always reads as a single story.
"""
import copy
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from atlas_tools import registry, settings
from atlas_tools.deploy import DeployError, run_deploy, test_connection
from atlas_tools.registry import CHOICE, DIR, FILE, FLAG, FLOAT, INT, TEXT
from atlas_tools.runner import TaskRun, app_root

PAD = 8
MAX_LOG_LINES = 6000


class ConfirmDialog(tk.Toplevel):
    """Modal confirm. If `phrase` is given, the user has to type it."""

    def __init__(self, parent, title, message, phrase=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.result = False

        frame = ttk.Frame(self, padding=PAD * 2)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=message, wraplength=440, justify="left").pack(
            anchor="w", pady=(0, PAD))

        self._entry = None
        if phrase:
            ttk.Label(frame, text=f'Type "{phrase}" to continue:').pack(anchor="w")
            self._entry = ttk.Entry(frame, width=40)
            self._entry.pack(anchor="w", pady=(2, PAD))
            self._entry.bind("<Return>", lambda _e: self._ok(phrase))

        row = ttk.Frame(frame)
        row.pack(anchor="e")
        ttk.Button(row, text="Cancel", command=self.destroy).pack(
            side="right", padx=(PAD, 0))
        ttk.Button(row, text="Continue",
                   command=lambda: self._ok(phrase)).pack(side="right")

        self.grab_set()
        (self._entry or self).focus_set()
        self.wait_window(self)

    def _ok(self, phrase):
        if phrase and self._entry.get().strip() != phrase:
            messagebox.showwarning(
                "Not confirmed", f'You need to type exactly: {phrase}',
                parent=self)
            return
        self.result = True
        self.destroy()


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=0)
        self.master = master
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.events = queue.Queue()
        self.run = None            # active TaskRun
        self.busy = False
        self._stop_flag = False
        self._task_widgets = {}    # param key -> (widget, var, row frame)
        self._values = {}          # param key -> tk var
        self.current_task = None
        self._selecting = False
        self._drain_id = None
        self._env_sources = {}
        self._target_labels = {}
        self._dirty = False
        self._building_settings = False

        try:
            self.settings = settings.load()
        except RuntimeError as exc:
            messagebox.showerror("deploy.json", str(exc))
            self.settings = settings.DEFAULTS

        self._build()
        self._select_task(registry.TASKS[0].id)
        self._drain_id = self.after(60, self._drain)

    # ------------------------------------------------------------------ build
    def _build(self):
        outer = ttk.Panedwindow(self, orient="vertical")
        outer.grid(row=0, column=0, sticky="nsew")

        top = ttk.Frame(outer)
        top.columnconfigure(0, weight=1)
        top.rowconfigure(0, weight=1)
        self.nb = ttk.Notebook(top)
        self.nb.grid(row=0, column=0, sticky="nsew")
        self.nb.add(self._build_run_tab(self.nb), text="  Run  ")
        self.nb.add(self._build_deploy_tab(self.nb), text="  Deploy  ")
        self.nb.add(self._build_settings_tab(self.nb), text="  Settings  ")

        bottom = self._build_log_pane(outer)

        outer.add(top, weight=3)
        outer.add(bottom, weight=4)

        self._build_status_bar()

    # --- run tab ---
    def _build_run_tab(self, parent):
        tab = ttk.Frame(parent, padding=PAD)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        split = ttk.Panedwindow(tab, orient="horizontal")
        split.grid(row=0, column=0, sticky="nsew")

        # left: the task tree
        left = ttk.Frame(split)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        tsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        tsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        for group in registry.GROUPS:
            gid = self.tree.insert("", "end", iid=f"g:{group}", text=group,
                                   open=True)
            for task in registry.TASKS:
                if task.group == group:
                    self.tree.insert(gid, "end", iid=task.id, text=task.label)

        # right: the generated form
        right = ttk.Frame(split)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        self.task_title = ttk.Label(right, text="", font=("", 12, "bold"))
        self.task_title.grid(row=0, column=0, sticky="w", padx=PAD)
        self.task_help = ttk.Label(right, text="", wraplength=560,
                                   justify="left", foreground="#555")
        self.task_help.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(2, PAD))

        self.form = ttk.LabelFrame(right, text="Options", padding=PAD)
        self.form.grid(row=2, column=0, sticky="nsew", padx=PAD)
        self.form.columnconfigure(1, weight=1)

        self.preview = ttk.Label(right, text="", foreground="#0a5", wraplength=560,
                                 justify="left", font=("Courier", 9))
        self.preview.grid(row=3, column=0, sticky="ew", padx=PAD, pady=(PAD, 2))

        actions = ttk.Frame(right)
        actions.grid(row=4, column=0, sticky="ew", padx=PAD, pady=(2, 0))
        self.run_btn = ttk.Button(actions, text="Run", command=self._start_task)
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text="Stop", command=self._stop,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=(PAD, 0))

        split.add(left, weight=1)
        split.add(right, weight=3)
        return tab

    # --- deploy tab ---
    def _build_deploy_tab(self, parent):
        tab = ttk.Frame(parent, padding=PAD * 2)
        tab.columnconfigure(0, weight=1)

        ttk.Label(tab, text="Push local files to the server over SFTP",
                  font=("", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(tab, wraplength=620, justify="left", foreground="#555",
                  text=("Each target has its own local folder, remote folder and "
                        "file patterns, set on the Settings tab. Unchanged files "
                        "are skipped. Nothing is ever deleted on the server.")
                  ).grid(row=1, column=0, sticky="ew", pady=(2, PAD))

        box = ttk.LabelFrame(tab, text="Targets", padding=PAD)
        box.grid(row=2, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)

        self.target_vars = {}
        for i, (key, target) in enumerate(self.settings["targets"].items()):
            var = tk.BooleanVar(value=bool(target.get("enabled", True)))
            self.target_vars[key] = var
            row = ttk.Frame(box)
            row.grid(row=i, column=0, sticky="ew", pady=2)
            ttk.Checkbutton(row, text=target.get("label", key),
                            variable=var).pack(side="left")
            lbl = ttk.Label(row, foreground="#555", font=("Courier", 9))
            lbl.pack(side="left", padx=(PAD, 0))
            self._target_labels[key] = lbl
            self._refresh_target_label(key)

        opts = ttk.LabelFrame(tab, text="This run", padding=PAD)
        opts.grid(row=3, column=0, sticky="ew", pady=(PAD, 0))

        self.dry_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Dry run (list what would upload, change nothing)",
                        variable=self.dry_var).grid(row=0, column=0, sticky="w")
        self.post_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Run post-deploy commands (npm install / build / pm2 restart)",
                        variable=self.post_var).grid(row=1, column=0, sticky="w")
        self.env_var = tk.BooleanVar(value=False)
        env_cb = ttk.Checkbutton(
            opts, variable=self.env_var,
            text="Also upload .env files  --  OVERWRITES production credentials",
            command=self._env_warn)
        env_cb.grid(row=2, column=0, sticky="w", pady=(PAD, 0))
        ttk.Label(opts, foreground="#a00", wraplength=620, justify="left",
                  text=("Leave this off for normal code pushes. The server's .env "
                        "usually differs from your local one (DB_HOST=localhost, "
                        "PACKAGE_DIR, production secrets), so uploading it can take "
                        "the server down.")
                  ).grid(row=3, column=0, sticky="ew", padx=(20, 0))

        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, sticky="ew", pady=(PAD * 2, 0))
        self.test_btn = ttk.Button(actions, text="Test connection",
                                   command=self._test_conn)
        self.test_btn.pack(side="left")
        self.deploy_btn = ttk.Button(actions, text="Deploy", command=self._deploy)
        self.deploy_btn.pack(side="left", padx=(PAD, 0))
        return tab

    def _refresh_target_label(self, key):
        target = self.settings["targets"].get(key) or {}
        lbl = self._target_labels.get(key)
        if lbl is not None:
            lbl.configure(
                text=f"{target.get('local') or '.'}  ->  {target.get('remote') or '(no remote set)'}")

    def _env_warn(self):
        if self.env_var.get():
            ok = ConfirmDialog(
                self.master, "Upload .env files?",
                "This will overwrite the .env files on the server with your local "
                "copies.\n\nThat is almost never what you want for a code push: "
                "the server's DB_HOST, PACKAGE_DIR and secrets are usually "
                "different from yours.",
                phrase="overwrite env").result
            if not ok:
                self.env_var.set(False)

    # --- settings tab ---
    def _build_settings_tab(self, parent):
        outer = ttk.Frame(parent)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        sb.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=sb.set)

        tab = ttk.Frame(canvas, padding=PAD * 2)
        window = canvas.create_window((0, 0), window=tab, anchor="nw")

        # These two handlers feed each other: setting the item width resizes the
        # frame, which fires <Configure>, which sets the scrollregion, which can
        # resize the canvas... Tk then never runs out of events and update()
        # blocks forever. Both guards below make each handler a no-op unless the
        # value genuinely changed, which terminates the cycle.
        def on_frame_configure(_event=None):
            bbox = canvas.bbox("all")
            if bbox is None:
                return
            want = " ".join(str(int(v)) for v in bbox)
            if str(canvas.cget("scrollregion")) != want:
                canvas.configure(scrollregion=want)

        def on_canvas_configure(event):
            if str(canvas.itemcget(window, "width")) != str(event.width):
                canvas.itemconfigure(window, width=event.width)

        tab.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        # Wheel scrolling only while the pointer is over this tab, rather than
        # bind_all, which would steal the wheel from the log pane too.
        def on_wheel(event):
            delta = event.delta
            if delta == 0:
                return
            canvas.yview_scroll(int(-delta / (120 if abs(delta) >= 120 else 1)),
                                "units")

        for widget in (canvas, tab):
            widget.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", on_wheel))
            widget.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        self._settings_canvas = canvas
        self._settings_fields_frame = tab
        self._build_settings_fields(tab)

        # --- footer, OUTSIDE the scroll area ---------------------------------
        # It lives here rather than at the bottom of the scrolling frame because
        # the field list is ~1270px tall in a ~435px viewport: a Save button
        # inside the canvas sits about 800px below the fold, so edits get made
        # and never saved. An always-visible footer is the whole point.
        footer = ttk.Frame(outer, padding=(0, PAD, 0, 0))
        footer.grid(row=1, column=0, columnspan=2, sticky="ew")
        footer.columnconfigure(2, weight=1)
        ttk.Button(footer, text="Save", command=self._save_settings).grid(
            row=0, column=0)
        ttk.Button(footer, text="Reload from .env / disk",
                   command=self._reload_settings).grid(row=0, column=1,
                                                       padx=(PAD, 0))
        self.settings_status = ttk.Label(footer, text="", foreground="#a05000")
        self.settings_status.grid(row=0, column=2, sticky="w", padx=(PAD, 0))
        ttk.Label(footer, foreground="#777",
                  text=os.path.basename(settings.path())).grid(
            row=0, column=3, sticky="e")
        return outer

    def _build_settings_fields(self, tab):
        """Build the field list. Called again by Reload to rebuild in place."""
        self._building_settings = True
        try:
            self._build_settings_fields_inner(tab)
        finally:
            self._building_settings = False
        self._dirty = False
        self._refresh_settings_status()

    def _build_settings_fields_inner(self, tab):
        for child in tab.winfo_children():
            child.destroy()
        tab.columnconfigure(1, weight=1)
        self.s_vars = {}
        self._dirty = False
        self._env_sources = settings.env_sources(self.settings)
        r = 0

        if self._env_sources:
            env_file = settings.env_path(self.settings)
            box = ttk.Frame(tab)
            box.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(0, PAD))
            ttk.Label(box, foreground="#060",
                      text=f"{len(self._env_sources)} setting(s) come from "
                           f"{env_file}").pack(anchor="w")
            ttk.Label(box, foreground="#777", wraplength=620, justify="left",
                      text="Those fields are shown read-only here -- .env wins "
                           "on every load, so editing them in the app would do "
                           "nothing. Change them in .env and press Reload."
                      ).pack(anchor="w")
            r += 1
        else:
            ttk.Label(tab, foreground="#777", wraplength=620, justify="left",
                      text=("Tip: SFTP_HOST, SFTP_USER, SFTP_PASSWORD, "
                            "SFTP_KEY_PATH, SCRAPER_DIR and ADMIN_SERVER_DIR can "
                            "be set in .env instead of here.")
                      ).grid(row=r, column=0, columnspan=3, sticky="ew",
                             pady=(0, PAD))
            r += 1

        ttk.Label(tab, text="Environment", font=("", 11, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(0, 4))
        r += 1
        r = self._setting_row(tab, r, "env_file", ".env file",
                              self.settings.get("env_file", ""), kind=FILE,
                              hint="Blank = the .env sitting next to this app.")

        ttk.Separator(tab, orient="horizontal").grid(
            row=r, column=0, columnspan=3, sticky="ew", pady=PAD)
        r += 1
        ttk.Label(tab, text="SSH connection", font=("", 11, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(0, 4))
        r += 1

        conn = self.settings["connection"]
        r = self._setting_row(tab, r, "connection.host", "Host", conn.get("host", ""))
        r = self._setting_row(tab, r, "connection.port", "Port", conn.get("port", 22))
        r = self._setting_row(tab, r, "connection.user", "Username",
                              conn.get("user", ""))
        auth = tk.StringVar(value=conn.get("auth", "key"))
        self.s_vars["connection.auth"] = auth
        auth.trace_add("write", lambda *_a: self._mark_dirty())
        ttk.Label(tab, text="Auth").grid(row=r, column=0, sticky="w", pady=2)
        arow = ttk.Frame(tab)
        arow.grid(row=r, column=1, columnspan=2, sticky="w")
        env_auth = "connection.auth" in self._env_sources
        state = "disabled" if env_auth else "normal"
        ttk.Radiobutton(arow, text="SSH key / agent", variable=auth,
                        value="key", state=state).pack(side="left")
        ttk.Radiobutton(arow, text="Password", variable=auth,
                        value="password", state=state).pack(side="left",
                                                            padx=(PAD, 0))
        if env_auth:
            ttk.Label(arow, foreground="#060",
                      text=f"  from .env ({self._env_sources['connection.auth']})"
                      ).pack(side="left")
        r += 1
        r = self._setting_row(tab, r, "connection.key_path", "Private key",
                              conn.get("key_path", ""), kind=FILE)
        r = self._setting_row(tab, r, "connection.password", "Password",
                              conn.get("password", ""), secret=True,
                              hint="Prefer SFTP_PASSWORD in .env, or a key.")

        opts = self.settings["options"]
        skip = tk.BooleanVar(value=bool(opts.get("skip_unchanged", True)))
        atomic = tk.BooleanVar(value=bool(opts.get("atomic", True)))
        self.s_vars["options.skip_unchanged"] = skip
        self.s_vars["options.atomic"] = atomic
        for var in (skip, atomic):
            var.trace_add("write", lambda *_a: self._mark_dirty())
        ttk.Checkbutton(tab, text="Skip files whose size and mtime already match",
                        variable=skip).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Checkbutton(tab, text="Upload to a temp name, then rename into place",
                        variable=atomic).grid(row=r, column=1, sticky="w")
        r += 1

        for key, target in self.settings["targets"].items():
            ttk.Separator(tab, orient="horizontal").grid(
                row=r, column=0, columnspan=3, sticky="ew", pady=PAD)
            r += 1
            ttk.Label(tab, text=f"Target: {target.get('label', key)}",
                      font=("", 11, "bold")).grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(0, 4))
            r += 1
            r = self._setting_row(tab, r, f"targets.{key}.local", "Local folder",
                                  target.get("local", ""), kind=DIR,
                                  hint="Relative to this app's folder.")
            r = self._setting_row(tab, r, f"targets.{key}.remote", "Remote folder",
                                  target.get("remote", ""))
            r = self._setting_multiline(tab, r, f"targets.{key}.include",
                                       "Include patterns",
                                       target.get("include", []), height=6)
            r = self._setting_multiline(tab, r, f"targets.{key}.exclude",
                                       "Exclude patterns",
                                       target.get("exclude", []), height=4)
            r = self._setting_multiline(tab, r, f"targets.{key}.env_files",
                                       ".env files",
                                       target.get("env_files", []), height=2,
                                       hint="Only uploaded when you tick the box on the Deploy tab.")
            r = self._setting_multiline(tab, r, f"targets.{key}.post_commands",
                                       "Post-deploy commands",
                                       target.get("post_commands", []), height=4,
                                       hint="One per line, run in order over SSH.")

    def _mark_dirty(self, *_args):
        if getattr(self, "_building_settings", False):
            return
        self._dirty = True
        self._refresh_settings_status()

    def _refresh_settings_status(self):
        if not hasattr(self, "settings_status"):
            return
        self.settings_status.configure(
            text="unsaved changes -- press Save" if getattr(self, "_dirty", False)
            else "")

    def _setting_row(self, tab, r, key, label, value, kind=TEXT, secret=False,
                     hint=""):
        env_var = self._env_sources.get(key)
        ttk.Label(tab, text=label).grid(row=r, column=0, sticky="w", pady=2)
        var = tk.StringVar(value="" if value is None else str(value))
        self.s_vars[key] = var
        var.trace_add("write", lambda *_a: self._mark_dirty())
        entry = ttk.Entry(tab, textvariable=var, show="*" if secret else "",
                          state="readonly" if env_var else "normal")
        entry.grid(row=r, column=1, sticky="ew", pady=2)
        if kind in (FILE, DIR) and not env_var:
            ttk.Button(tab, text="...", width=3,
                       command=lambda v=var, k=kind: self._browse(v, k)).grid(
                row=r, column=2, sticky="w", padx=(4, 0))
        r += 1
        note = f"from .env ({env_var})" if env_var else hint
        if note:
            ttk.Label(tab, text=note,
                      foreground="#060" if env_var else "#777").grid(
                row=r, column=1, sticky="w")
            r += 1
        return r

    def _setting_multiline(self, tab, r, key, label, value, height=4, hint=""):
        ttk.Label(tab, text=label).grid(row=r, column=0, sticky="nw", pady=2)
        text = tk.Text(tab, height=height, wrap="none", font=("Courier", 9))
        text.insert("1.0", "\n".join(value or []))
        text.grid(row=r, column=1, columnspan=2, sticky="ew", pady=2)
        text.bind("<KeyRelease>", self._mark_dirty)
        self.s_vars[key] = text
        r += 1
        if hint:
            ttk.Label(tab, text=hint, foreground="#777").grid(
                row=r, column=1, sticky="w")
            r += 1
        return r

    def _browse(self, var, kind):
        if kind == DIR:
            path = filedialog.askdirectory(initialdir=app_root())
        else:
            path = filedialog.askopenfilename(initialdir=app_root())
        if path:
            var.set(path)

    # --- log pane ---
    def _build_log_pane(self, parent):
        frame = ttk.Frame(parent, padding=(PAD, 0, PAD, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        ttk.Label(header, text="Output", font=("", 10, "bold")).pack(side="left")
        ttk.Button(header, text="Clear", command=self._clear_log).pack(side="right")
        ttk.Button(header, text="Save to file...",
                   command=self._save_log).pack(side="right", padx=(0, 4))

        self.log = ScrolledText(frame, height=14, wrap="word", state="disabled",
                                font=("Consolas", 9), background="#1c1c1c",
                                foreground="#d8d8d8", insertbackground="#d8d8d8")
        self.log.grid(row=1, column=0, sticky="nsew")
        self.log.tag_configure("err", foreground="#ff8b7a")
        self.log.tag_configure("warn", foreground="#ffcf6b")
        self.log.tag_configure("ok", foreground="#8fe08f")
        self.log.tag_configure("cmd", foreground="#7fc8ff")
        self.log.tag_configure("prompt", foreground="#ffd479")

        # prompt bar: hidden until a task blocks on input()
        self.prompt_bar = ttk.Frame(frame, padding=(0, PAD, 0, PAD))
        self.prompt_bar.columnconfigure(1, weight=1)
        self.prompt_label = ttk.Label(self.prompt_bar, text="", font=("", 10, "bold"),
                                      foreground="#a05000")
        self.prompt_label.grid(row=0, column=0, sticky="w")
        self.prompt_entry = ttk.Entry(self.prompt_bar)
        self.prompt_entry.grid(row=0, column=1, sticky="ew", padx=PAD)
        self.prompt_entry.bind("<Return>", lambda _e: self._send_prompt())
        self.prompt_send = ttk.Button(self.prompt_bar, text="Send",
                                      command=self._send_prompt)
        self.prompt_send.grid(row=0, column=2)
        self.prompt_quick = ttk.Frame(self.prompt_bar)
        self.prompt_quick.grid(row=0, column=3, padx=(PAD, 0))
        return frame

    def _build_status_bar(self):
        bar = ttk.Frame(self, padding=(PAD, 2))
        bar.grid(row=1, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.status = ttk.Label(bar, text="Ready", anchor="w")
        self.status.grid(row=0, column=0, sticky="ew")
        env = settings.resolved_env_file(self.settings) or os.path.join(
            app_root(), ".env")
        marker = "" if os.path.exists(env) else "  [NOT FOUND]"
        ttk.Label(bar, foreground="#777",
                  text=f".env: {env}{marker}").grid(row=0, column=1, sticky="e")

    # ------------------------------------------------------------- task form
    def _on_tree_select(self, _event=None):
        if self._selecting:
            return
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid.startswith("g:"):
            return
        self._select_task(iid)

    def _select_task(self, task_id):
        # Re-entrancy guard. selection_set() below fires <<TreeviewSelect>>,
        # which lands back here -- without this the two call each other for
        # ever, rebuilding the form every pass, and Tk never runs out of events
        # so the window never finishes drawing.
        if self._selecting:
            return
        self._selecting = True
        try:
            self._build_task_form(task_id)
        finally:
            self._selecting = False

    def _build_task_form(self, task_id):
        task = registry.BY_ID[task_id]
        self.current_task = task
        if self.tree.selection() != (task_id,):
            try:
                self.tree.selection_set(task_id)
            except tk.TclError:
                pass

        notes = []
        if task.danger:
            notes.append("DESTRUCTIVE: " + (task.danger_note or ""))
        if task.interactive:
            notes.append("Interactive: it will ask questions in the bar below "
                         "the log.")
        if task.long_running:
            notes.append("Long-running: use Stop to end it.")
        self.task_title.configure(text=task.label)
        self.task_help.configure(
            text="\n".join([task.help] + notes).strip())

        for child in self.form.winfo_children():
            child.destroy()
        self._values = {}
        self._task_widgets = {}

        if not task.params:
            ttk.Label(self.form, text="No options.", foreground="#777").grid(
                row=0, column=0, sticky="w")

        for i, p in enumerate(task.params):
            holder = ttk.Frame(self.form)
            holder.grid(row=i, column=0, columnspan=3, sticky="ew")
            holder.columnconfigure(1, weight=1)

            if p.kind == FLAG:
                var = tk.BooleanVar(value=bool(p.default))
                ttk.Checkbutton(holder, text=p.label, variable=var).grid(
                    row=0, column=0, columnspan=2, sticky="w", pady=2)
            elif p.kind == CHOICE:
                var = tk.StringVar(value=p.default or (p.choices or [""])[0])
                ttk.Label(holder, text=p.label).grid(row=0, column=0, sticky="w",
                                                     pady=2)
                combo = ttk.Combobox(holder, textvariable=var, state="readonly",
                                     values=list(p.choices or []))
                combo.grid(row=0, column=1, sticky="w", pady=2)
            else:
                var = tk.StringVar(value="" if p.default is None else str(p.default))
                ttk.Label(holder, text=p.label).grid(row=0, column=0, sticky="w",
                                                     pady=2)
                entry = ttk.Entry(holder, textvariable=var, width=28)
                entry.grid(row=0, column=1, sticky="w", pady=2)
                if p.kind in (FILE, DIR):
                    ttk.Button(holder, text="...", width=3,
                               command=lambda v=var, k=p.kind: self._browse(v, k)
                               ).grid(row=0, column=2, sticky="w", padx=(4, 0))

            if p.help:
                ttk.Label(holder, text=p.help, foreground="#777",
                          wraplength=430, justify="left").grid(
                    row=1, column=1, sticky="w")

            var.trace_add("write", lambda *_a: self._refresh_form())
            self._values[p.key] = var
            self._task_widgets[p.key] = holder

        self._refresh_form()

    def _form_values(self):
        return {k: v.get() for k, v in self._values.items()}

    def _refresh_form(self):
        """Show/hide conditional params and update the command preview."""
        if self.current_task is None:
            return
        values = self._form_values()
        for p in self.current_task.params:
            holder = self._task_widgets.get(p.key)
            if holder is None:
                continue
            if registry.visible(p, values):
                if not holder.winfo_ismapped():
                    holder.grid()
            else:
                holder.grid_remove()
        try:
            self.preview.configure(
                text=registry.preview(self.current_task, values))
        except Exception as exc:
            self.preview.configure(text=f"(cannot build command: {exc})")

    # ----------------------------------------------------------- run a task
    def _needs_confirm(self, task, values):
        if not task.danger:
            return None
        if task.id == "backup":
            return ("Rebuild master package?",
                    "This TRUNCATES the `updates` table and rebuilds a full base "
                    "package. Every client will then re-download a full package.",
                    "rebuild")
        if values.get("apply"):
            return (f"Apply {task.label}?",
                    (task.danger_note or "") +
                    "\n\nThis writes to the production database.",
                    "apply")
        if task.id == "reconcile_lc" and values.get("cmd") == "defer" \
                and not values.get("defer_dry"):
            return ("Run defer for real?",
                    "Bulk-parks LC games and DELETES the lewdcorner row plus the "
                    "orphaned LC-only atlas row for every match at or above the "
                    "threshold. No prompts.",
                    "defer")
        return None

    def _start_task(self):
        if self.busy:
            messagebox.showinfo("Busy", "Something is already running.")
            return
        task = self.current_task
        values = self._form_values()

        try:
            argv = registry.build_argv(task, values)
        except Exception as exc:
            messagebox.showerror("Bad options", str(exc))
            return

        # required positionals
        for p in task.params:
            if p.positional and p.kind != FLAG and registry.visible(p, values) \
                    and "Required" in (p.help or "") \
                    and not str(values.get(p.key, "")).strip():
                messagebox.showerror("Missing value", f"{p.label} is required.")
                return

        confirm = self._needs_confirm(task, values)
        if confirm:
            title, message, phrase = confirm
            if not ConfirmDialog(self.master, title, message, phrase).result:
                return

        self._set_busy(True, f"Running {task.label}")
        self._log(f"\n$ {registry.preview(task, values)}\n", "cmd")

        self.run = TaskRun(task.id, argv,
                           env_file=settings.resolved_env_file(self.settings))
        self.run.start()

    def _stop(self):
        self._stop_flag = True
        if self.run is not None and self.run.running:
            self._log("\n[stopping...]\n", "warn")
            self.run.stop()

    def _set_busy(self, busy, status="Ready"):
        self.busy = busy
        self.status.configure(text=status)
        state = "disabled" if busy else "normal"
        self.run_btn.configure(state=state)
        self.deploy_btn.configure(state=state)
        self.test_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if busy else "disabled")
        if not busy:
            self._hide_prompt()
            self._stop_flag = False

    # ---------------------------------------------------------------- prompts
    def _show_prompt(self, text):
        self.prompt_label.configure(text=text.strip() or "input:")
        self.prompt_bar.grid(row=2, column=0, sticky="ew")
        for child in self.prompt_quick.winfo_children():
            child.destroy()
        low = text.lower()
        if "[y/n]" in low:
            ttk.Button(self.prompt_quick, text="Yes", width=5,
                       command=lambda: self._send_prompt("y")).pack(side="left")
            ttk.Button(self.prompt_quick, text="No", width=5,
                       command=lambda: self._send_prompt("n")).pack(
                side="left", padx=(4, 0))
        elif "choose" in low:
            ttk.Button(self.prompt_quick, text="skip", width=6,
                       command=lambda: self._send_prompt("s")).pack(side="left")
            ttk.Button(self.prompt_quick, text="quit", width=6,
                       command=lambda: self._send_prompt("q")).pack(
                side="left", padx=(4, 0))
        self.prompt_entry.focus_set()

    def _hide_prompt(self):
        self.prompt_bar.grid_remove()
        self.prompt_entry.delete(0, "end")

    def _send_prompt(self, forced=None):
        if self.run is None:
            return
        text = forced if forced is not None else self.prompt_entry.get()
        self._log(f"> {text}\n", "prompt")
        self.run.send_line(text)
        self._hide_prompt()

    # ----------------------------------------------------------------- deploy
    def _selected_targets(self):
        return [k for k, v in self.target_vars.items() if v.get()]

    def _deploy(self):
        if self.busy:
            messagebox.showinfo("Busy", "Something is already running.")
            return
        targets = self._selected_targets()
        if not targets:
            messagebox.showerror("No targets", "Tick at least one target.")
            return
        dry = self.dry_var.get()
        if not dry:
            names = ", ".join(
                self.settings["targets"][k].get("label", k) for k in targets)
            extra = "\n\nIt will ALSO overwrite the remote .env files." \
                if self.env_var.get() else ""
            if not ConfirmDialog(
                    self.master, "Deploy for real?",
                    f"Upload to: {names}{extra}", "deploy").result:
                return

        self._set_busy(True, "Deploying" if not dry else "Dry run")
        threading.Thread(target=self._deploy_worker,
                         args=(targets, dry), daemon=True).start()

    def _deploy_worker(self, targets, dry):
        def log(line):
            self.events.put(("out", str(line) + "\n"))
        try:
            run_deploy(self.settings, targets,
                       include_env=self.env_var.get(),
                       dry_run=dry,
                       run_post=self.post_var.get(),
                       log=log,
                       should_stop=lambda: self._stop_flag)
        except DeployError as exc:
            self.events.put(("out", f"\nDEPLOY FAILED: {exc}\n"))
        except Exception as exc:
            self.events.put(("out", f"\nDEPLOY ERROR: {exc!r}\n"))
        finally:
            self.events.put(("exit", None))

    def _test_conn(self):
        if self.busy:
            return
        self._set_busy(True, "Testing connection")

        def worker():
            def log(line):
                self.events.put(("out", str(line) + "\n"))
            try:
                test_connection(self.settings, log=log)
            except DeployError as exc:
                self.events.put(("out", f"\nFAILED: {exc}\n"))
            except Exception as exc:
                self.events.put(("out", f"\nERROR: {exc!r}\n"))
            finally:
                self.events.put(("exit", None))

        threading.Thread(target=worker, daemon=True).start()

    # --------------------------------------------------------------- settings
    def _collect_settings(self):
        # Deep-copied so that editing the form can't mutate self.settings in
        # place -- these are nested dicts, and a shallow copy shares
        # `connection` and `options` with the live settings.
        data = {k: copy.deepcopy(v) for k, v in self.settings.items()
                if k != "targets"}
        data["targets"] = {}
        for key, target in self.settings["targets"].items():
            data["targets"][key] = {
                k: copy.deepcopy(v) for k, v in target.items()}

        for key, widget in self.s_vars.items():
            # Env-controlled fields are read-only in the form; writing them back
            # would just store a copy of the .env value in deploy.json.
            if key in self._env_sources:
                continue
            if isinstance(widget, tk.Text):
                value = [ln.strip() for ln in
                         widget.get("1.0", "end").splitlines() if ln.strip()]
            else:
                value = widget.get()
            parts = key.split(".")
            node = data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            leaf = parts[-1]
            if leaf == "port":
                try:
                    value = int(str(value).strip() or 22)
                except ValueError:
                    value = 22
            node[leaf] = value

        for key in data["targets"]:
            if key in self.target_vars:
                data["targets"][key]["enabled"] = self.target_vars[key].get()
        return data

    def _save_settings(self):
        try:
            data = self._collect_settings()
            path = settings.save(data, env_controlled=self._env_sources)
        except Exception as exc:
            messagebox.showerror(
                "Save failed",
                f"{exc}\n\nTried to write:\n{settings.path()}")
            return
        self.settings = data
        for k in self.settings["targets"]:
            self._refresh_target_label(k)
        # Re-apply .env on top, so what the deploy uses matches what a fresh
        # load() would produce.
        settings.apply_env(self.settings)
        self._dirty = False
        self._refresh_settings_status()
        self._log(f"settings saved to {path}\n", "ok")
        self.status.configure(text="Settings saved")

    def _reload_settings(self):
        """Re-read .env + deploy.json and rebuild the fields in place."""
        if self._dirty and not messagebox.askyesno(
                "Reload", "Discard unsaved changes and reload from "
                          ".env / deploy.json?"):
            return
        try:
            fresh = settings.load()
        except RuntimeError as exc:
            messagebox.showerror("Reload failed", str(exc))
            return
        self.settings = fresh
        self._build_settings_fields(self._settings_fields_frame)
        for key in self.settings["targets"]:
            self._refresh_target_label(key)
        self._log(f"settings reloaded from {settings.env_path(self.settings)} "
                  f"and {settings.path()}\n", "ok")
        self.status.configure(text="Settings reloaded")

    # -------------------------------------------------------------------- log
    def _log(self, text, tag=None):
        self.log.configure(state="normal")
        at_bottom = self.log.yview()[1] > 0.999
        self.log.insert("end", text, tag or ())
        # Keep the widget from growing without bound on a long crawl.
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > MAX_LOG_LINES:
            self.log.delete("1.0", f"{lines - MAX_LOG_LINES}.0")
        self.log.configure(state="disabled")
        if at_bottom:
            self.log.see("end")

    def _tag_for(self, line):
        low = line.lower()
        if line.startswith("$ "):
            return "cmd"
        if any(w in line for w in ("Traceback", "ERROR", "FAILED", "!!")) or \
                "error" in low[:40]:
            return "err"
        if line.lstrip().startswith(("WARN", "warning", "Warning")) or \
                "skipping" in low:
            return "warn"
        if line.startswith("  + ") or "done" in low[:8] or "OK" in line[:12]:
            return "ok"
        return None

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _save_log(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialdir=app_root(),
            initialfile="atlas-tools-log.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log.get("1.0", "end"))
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.status.configure(text=f"Log saved to {path}")

    # ------------------------------------------------------------------ pump
    def _drain(self):
        """Move queued events onto the widgets. Runs on the Tk thread."""
        for source in (self.events,
                       self.run.events if self.run is not None else None):
            if source is None:
                continue
            handled = 0
            while handled < 400:
                try:
                    kind, payload = source.get_nowait()
                except queue.Empty:
                    break
                handled += 1
                if kind == "out":
                    for line in str(payload).splitlines(keepends=True):
                        self._log(line, self._tag_for(line))
                elif kind == "prompt":
                    self._show_prompt(payload)
                elif kind == "exit":
                    if payload is None:
                        self._log("\n", None)
                        self._set_busy(False)
                    else:
                        tag = "ok" if payload == 0 else "err"
                        self._log(f"\n[exit code {payload}]\n", tag)
                        self._set_busy(False, f"Finished (exit {payload})")
                        self.run = None
        # Reschedule, tracking the id so shutdown() can cancel it. Without that,
        # destroying the window leaves a pending timer that fires against a gone
        # widget and prints 'invalid command name ..._drain'.
        try:
            self._drain_id = self.after(60, self._drain)
        except tk.TclError:
            self._drain_id = None

    def shutdown(self):
        """Cancel timers and kill any child before the window goes away."""
        if self._drain_id is not None:
            try:
                self.after_cancel(self._drain_id)
            except tk.TclError:
                pass
            self._drain_id = None
        if self.run is not None:
            self.run.stop()


def launch():
    root = tk.Tk()
    root.title("Atlas Tools")
    root.geometry("1040x760")
    root.minsize(820, 560)
    try:
        # Slightly less dated-looking on Windows.
        ttk.Style().theme_use("vista" if sys.platform == "win32" else "clam")
    except tk.TclError:
        pass
    app = App(root)

    def on_close():
        if app.busy and not messagebox.askyesno(
                "Quit", "Something is still running. Stop it and quit?"):
            return
        app.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0
