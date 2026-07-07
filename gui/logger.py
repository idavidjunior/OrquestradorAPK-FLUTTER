#!/usr/bin/env python3
"""Thread-safe logger for GUI with queue-based draining."""

import queue
from datetime import datetime


class Logger:
    """
    Thread-safe logger that writes to a CTkTextbox from the main thread.
    Any thread calls .put(); a periodic timer drains the queue in the mainloop.
    """

    ICONS = {"ok": "\u2705", "err": "\u274c", "warn": "\u26a0\ufe0f",
             "info": "\u2139\ufe0f", "sep": "\u2500"}

    def __init__(self, textbox):
        from customtkinter import CTkTextbox
        self._box = textbox
        self._q: queue.Queue = queue.Queue()
        self._drain()

    def _drain(self):
        try:
            count = 0
            while count < 30:
                level, msg = self._q.get_nowait()
                ts = datetime.now().strftime("%H:%M:%S")
                icon = self.ICONS.get(level, "\u2022")
                if level != "sep":
                    line = f"[{ts}] {icon}  {msg}\n"
                else:
                    line = f"\u2500" * 60 + "\n"
                self._box.configure(state="normal")
                self._box.insert("end", line)
                self._box.see("end")
                self._box.configure(state="disabled")
                count += 1
        except queue.Empty:
            pass
        except Exception:
            pass
        self._box.after(40, self._drain)

    def put(self, msg: str, level: str = "info"):
        self._q.put((level, msg))

    def sep(self):
        self._q.put(("sep", ""))

    def ok(self, msg):
        self.put(msg, "ok")

    def err(self, msg):
        self.put(msg, "err")

    def warn(self, msg):
        self.put(msg, "warn")

    def info(self, msg):
        self.put(msg, "info")
