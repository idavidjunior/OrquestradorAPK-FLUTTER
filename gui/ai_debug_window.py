import tkinter as tk
from tkinter import ttk
from datetime import datetime
from typing import Optional

from gui.ai_debug import get_debug_logger


class AIDebugWindow:
    """Janela de debug que mostra o dialogo completo entre orquestrador e IA."""

    def __init__(self, master):
        try:
            import customtkinter as ctk
        except ImportError:
            ctk = None
        self.ctk = ctk
        self.master = master
        self._window = None
        self._logger = get_debug_logger()
        self._logger.on_new_entry(self._on_new_entry)

    def show(self):
        if self._window is not None and self._window.winfo_exists():
            self._window.lift()
            self._window.focus_force()
            return
        self._build_window()
        self._refresh_list()

    def _build_window(self):
        ctk = self.ctk
        if ctk is None:
            return
        w = ctk.CTkToplevel(self.master)
        w.title("Debug da Conversa com IA")
        w.geometry("1100x650")
        w.minsize(800, 500)
        w.transient(self.master)
        w.protocol("WM_DELETE_WINDOW", self._close)
        self._window = w

        w.grid_rowconfigure(0, weight=1)
        w.grid_columnconfigure(1, weight=1)

        # ── Lista de entradas (esquerda) ──
        list_frame = ctk.CTkFrame(w, width=300)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(5, 2), pady=5)
        list_frame.grid_rowconfigure(1, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(list_frame, text="Conversas com IA",
                      font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, pady=(5, 2))

        self._listbox = tk.Listbox(
            list_frame, width=40, font=("Consolas", 10),
            selectbackground="#2E7D32", selectforeground="white",
        )
        self._listbox.grid(row=1, column=0, sticky="nsew", padx=5, pady=2)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        btn_frame = ctk.CTkFrame(list_frame, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=5, pady=5, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(btn_frame, text="Atualizar", command=self._refresh_list
                      ).grid(row=0, column=0, padx=(0, 2), sticky="ew")
        ctk.CTkButton(btn_frame, text="Limpar", fg_color="#C62828",
                      command=self._clear_all).grid(row=0, column=1, padx=(2, 0), sticky="ew")

        # ── Painel de detalhes (direita) ──
        detail_frame = ctk.CTkFrame(w)
        detail_frame.grid(row=0, column=1, sticky="nsew", padx=(2, 5), pady=5)
        detail_frame.grid_rowconfigure(2, weight=1)
        detail_frame.grid_columnconfigure(0, weight=1)

        self._lbl_header = ctk.CTkLabel(
            detail_frame, text="Selecione uma conversa na lista",
            font=ctk.CTkFont(size=12),
        )
        self._lbl_header.grid(row=0, column=0, padx=10, pady=(5, 2), sticky="w")

        self._tabview = ctk.CTkTabview(detail_frame)
        self._tabview.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)

        # Abas
        tab_prompt = self._tabview.add("Prompt Enviado")
        tab_response = self._tabview.add("Resposta Bruta")
        tab_extracted = self._tabview.add("Codigo Extraido")

        self._txt_prompt = ctk.CTkTextbox(tab_prompt, wrap="word", font=("Consolas", 11))
        self._txt_prompt.pack(fill="both", expand=True, padx=5, pady=5)
        self._txt_prompt.configure(state="disabled")

        self._txt_response = ctk.CTkTextbox(tab_response, wrap="word", font=("Consolas", 11))
        self._txt_response.pack(fill="both", expand=True, padx=5, pady=5)
        self._txt_response.configure(state="disabled")

        self._txt_extracted = ctk.CTkTextbox(tab_extracted, wrap="word", font=("Consolas", 11))
        self._txt_extracted.pack(fill="both", expand=True, padx=5, pady=5)
        self._txt_extracted.configure(state="disabled")

        self._selected_id = None

    def _on_new_entry(self, entry):
        if self._window is not None and self._window.winfo_exists():
            self._refresh_list()

    def _refresh_list(self):
        if self._window is None or not self._window.winfo_exists():
            return
        self._listbox.delete(0, "end")
        for e in self._logger.entries:
            ts = e["timestamp"][11:19] if len(e["timestamp"]) > 19 else e["timestamp"]
            ok = "OK" if e["success"] else "FAIL"
            label = f"[{ts}] {e['provider']}/{e['model'][:20]} tier={e['tier']} {ok}"
            self._listbox.insert("end", label)
            color = "#2E7D32" if e["success"] else "#C62828"
            self._listbox.itemconfig("end", fg=color)
        self._update_header()

    def _update_header(self):
        s = self._logger.summary()
        self._lbl_header.configure(
            text=f"Total: {s['total']} | Sucesso: {s['success']} | "
                 f"Falha: {s['failed']} | Media: {s['avg_elapsed']:.1f}s"
        )

    def _on_select(self, event):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        entries = self._logger.entries
        if idx < 0 or idx >= len(entries):
            return
        e = entries[idx]
        self._selected_id = e["id"]

        for txt, content in [
            (self._txt_prompt, e["prompt"]),
            (self._txt_response, e["response"]),
            (self._txt_extracted, e["extracted_code"] or "(nada extraido)"),
        ]:
            txt.configure(state="normal")
            txt.delete("0.0", "end")
            txt.insert("0.0", content)
            txt.configure(state="disabled")

        # Destaca na lista
        self._lbl_header.configure(
            text=f"{e['provider']}/{e['model']} | tier {e['tier']} | "
                 f"{e['elapsed']:.1f}s | {'SUCESSO' if e['success'] else 'FALHA'} | "
                 f"prompt: {e['prompt_size']} chars | response: {e['response_size']} chars"
        )

    def _clear_all(self):
        self._logger.clear()
        self._refresh_list()
        for txt in [self._txt_prompt, self._txt_response, self._txt_extracted]:
            txt.configure(state="normal")
            txt.delete("0.0", "end")
            txt.configure(state="disabled")
        self._lbl_header.configure(text="Nenhuma conversa registrada")

    def _close(self):
        self._window.destroy()
        self._window = None

    def close(self):
        self._close()
