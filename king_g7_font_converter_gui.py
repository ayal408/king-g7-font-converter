from __future__ import annotations

import argparse
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import ttf_to_king_lib as core


APP_TITLE = "׳׳׳™׳¨ ׳₪׳•׳ ׳˜׳™׳ ׳-KING G7"
SUPPORTED_EXTENSIONS = {".ttf", ".otf", ".ttc"}

# Header and Unicode map from a known-good KING G7 vector SFON library.
# Glyph data is not embedded; every output glyph is generated from the selected font.
EMBEDDED_TEMPLATE = bytes.fromhex(
    "73666f6e000000016c61746e00030001000108000000002c0000000000000000"
    "00000000000000000000007000000001000300010000000c000400380000000a"
    "0008000200020040005f05c705eaffff00000020005b059105d0ffffffe1ffc7"
    "fa96fa8e0001000000000000000000006c000000000000000000000000000000"
    "00000000001e20036c000079000001ec0001007800000000"
)


def convert_paths(paths: list[Path], output: Path, report) -> tuple[int, int]:
    output.mkdir(parents=True, exist_ok=True)
    used = {path.stem.casefold() for path in output.glob("*.lib")}
    converted = 0
    skipped = 0

    for path in paths:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            skipped += 1
            report(f"׳“׳™׳׳•׳’: {path.name} - ׳¡׳•׳’ ׳§׳•׳‘׳¥ ׳׳ ׳ ׳×׳׳")
            continue
        if path.suffix.lower() == ".ttc":
            try:
                faces = core.collection_faces(path)
            except Exception as exc:
                skipped += 1
                report(f"׳“׳™׳׳•׳’: {path.name} - {exc}")
                continue
        else:
            faces = [(0, path.stem)]

        for face_index, face_label in faces:
            face_path = path.with_name(f"{face_label}{path.suffix}")
            destination = core.unique_destination(output, face_path, used)
            face_name = path.name if len(faces) == 1 else f"{path.name} (׳₪׳ ׳™׳ {face_index + 1})"
            try:
                result = core.convert_font(
                    path,
                    destination,
                    EMBEDDED_TEMPLATE,
                    face_index=face_index,
                )
                core.validate_lib(destination.read_bytes())
                converted += 1
                report(
                    f"׳”׳•׳׳¨: {face_name} -> {destination.name} "
                    f"({result.glyphs_with_outlines} ׳×׳•׳•׳™׳ ׳‘׳¢׳׳™ ׳§׳•׳•׳™ ׳׳×׳׳¨)"
                )
            except Exception as exc:
                if destination.exists():
                    destination.unlink()
                skipped += 1
                report(f"׳“׳™׳׳•׳’: {face_name} - {exc}")

    return converted, skipped


class ConverterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("760x560")
        self.root.minsize(640, 460)
        self.paths: list[Path] = []
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text=APP_TITLE, font=("Segoe UI", 18, "bold"), anchor="e")
        title.pack(fill="x", pady=(0, 6))
        subtitle = ttk.Label(
            outer,
            text="׳‘׳—׳¨׳• ׳§׳•׳‘׳¦׳™ TTF / OTF / TTC. ׳”׳×׳•׳›׳ ׳” ׳×׳™׳¦׳•׳¨ ׳§׳•׳‘׳¦׳™ LIB ׳”׳׳×׳׳™׳׳™׳ ׳-KING G7.",
            anchor="e",
        )
        subtitle.pack(fill="x", pady=(0, 12))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="׳‘׳—׳¨ ׳₪׳•׳ ׳˜׳™׳", command=self.choose_fonts).pack(side="right")
        ttk.Button(buttons, text="׳ ׳§׳” ׳¨׳©׳™׳׳”", command=self.clear_fonts).pack(side="right", padx=8)

        self.file_list = tk.Listbox(outer, height=9, selectmode="extended")
        self.file_list.pack(fill="both", expand=False, pady=(0, 12))

        output_row = ttk.Frame(outer)
        output_row.pack(fill="x", pady=(0, 10))
        ttk.Label(output_row, text="׳×׳™׳§׳™׳™׳× ׳₪׳׳˜:").pack(side="right")
        self.output_var = tk.StringVar()
        ttk.Entry(output_row, textvariable=self.output_var).pack(side="right", fill="x", expand=True, padx=8)
        ttk.Button(output_row, text="׳‘׳—׳¨ ׳×׳™׳§׳™׳™׳”", command=self.choose_output).pack(side="left")

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(0, 10))
        self.convert_button = ttk.Button(action_row, text="׳”׳׳¨ ׳¢׳›׳©׳™׳•", command=self.start_conversion)
        self.convert_button.pack(side="right")
        self.progress = ttk.Progressbar(action_row, mode="indeterminate")
        self.progress.pack(side="right", fill="x", expand=True, padx=(0, 12))

        ttk.Label(outer, text="׳“׳•׳´׳—:", anchor="e").pack(fill="x")
        self.log = tk.Text(outer, height=10, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)

        self.root.after(100, self.poll_events)

    def choose_fonts(self):
        selected = filedialog.askopenfilenames(
            title="׳‘׳—׳¨ ׳₪׳•׳ ׳˜׳™׳",
            filetypes=[
                ("Font files", "*.ttf *.otf *.ttc"),
                ("TrueType", "*.ttf"),
                ("OpenType", "*.otf"),
                ("TrueType Collection", "*.ttc"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        known = {str(path).casefold() for path in self.paths}
        for item in selected:
            path = Path(item)
            if str(path).casefold() not in known:
                self.paths.append(path)
                known.add(str(path).casefold())
                self.file_list.insert("end", str(path))
        if not self.output_var.get() and self.paths:
            self.output_var.set(str(self.paths[0].parent / "KING G7 - LIB"))

    def clear_fonts(self):
        self.paths.clear()
        self.file_list.delete(0, "end")

    def choose_output(self):
        chosen = filedialog.askdirectory(title="׳‘׳—׳¨ ׳×׳™׳§׳™׳™׳× ׳₪׳׳˜")
        if chosen:
            self.output_var.set(chosen)

    def append_log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start_conversion(self):
        if not self.paths:
            messagebox.showwarning(APP_TITLE, "׳™׳© ׳׳‘׳—׳•׳¨ ׳׳₪׳—׳•׳× ׳§׳•׳‘׳¥ ׳₪׳•׳ ׳˜ ׳׳—׳“.")
            return
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning(APP_TITLE, "׳™׳© ׳׳‘׳—׳•׳¨ ׳×׳™׳§׳™׳™׳× ׳₪׳׳˜.")
            return

        output = Path(output_text)
        paths = list(self.paths)
        self.convert_button.configure(state="disabled")
        self.progress.start(12)
        self.append_log("׳׳×׳—׳™׳ ׳”׳׳¨׳”...")

        def worker():
            try:
                converted, skipped = convert_paths(
                    paths,
                    output,
                    lambda value: self.events.put(("log", value)),
                )
                self.events.put(("done", (converted, skipped, output)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def poll_events(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "log":
                    self.append_log(str(value))
                elif event == "done":
                    converted, skipped, output = value
                    self.progress.stop()
                    self.convert_button.configure(state="normal")
                    summary = f"׳”׳¡׳×׳™׳™׳: {converted} ׳”׳•׳׳¨׳•, {skipped} ׳“׳•׳׳’׳•.\n׳×׳™׳§׳™׳™׳”: {output}"
                    self.append_log(summary)
                    messagebox.showinfo(APP_TITLE, summary)
                elif event == "error":
                    self.progress.stop()
                    self.convert_button.configure(state="normal")
                    self.append_log(f"׳©׳’׳™׳׳”: {value}")
                    messagebox.showerror(APP_TITLE, str(value))
        except queue.Empty:
            pass
        self.root.after(100, self.poll_events)


def cli_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="KING G7 font converter")
    parser.add_argument("fonts", nargs="+", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    converted, skipped = convert_paths(args.fonts, args.output, print)
    print(f"Converted: {converted}; skipped: {skipped}; output: {args.output}")
    return 0 if converted else 1


def main() -> int:
    if len(sys.argv) > 1:
        return cli_main(sys.argv[1:])
    root = tk.Tk()
    try:
        root.option_add("*Font", ("Segoe UI", 10))
    except Exception:
        pass
    ConverterApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

