from __future__ import annotations

import argparse
import logging
import shutil
import threading
import traceback
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

try:
    from PIL import Image
except ImportError:
    Image = None


GIF_HEADERS = (b"GIF87a", b"GIF89a")
DEFAULT_OUTPUT_NAME = "output"


@dataclass
class RecoverStats:
    scanned: int = 0
    already_gif: int = 0
    recovered: int = 0
    animated: int = 0
    static: int = 0
    unknown: int = 0
    errors: int = 0


def is_gif_header(data: bytes) -> bool:
    return len(data) >= 6 and data[:6] in GIF_HEADERS


def restore_marketface(data: bytes) -> bytes:
    """Apply the QQNT 20-byte XOR + 30-byte plaintext cycle."""
    restored = bytearray(data)
    for offset in range(0, len(restored), 50):
        end = min(offset + 20, len(restored))
        for index in range(offset, end):
            restored[index] ^= 0xFF
    return bytes(restored)


def validate_gif(data: bytes) -> int:
    """Validate a GIF in memory without re-encoding it. Returns frame count."""
    if Image is None:
        raise RuntimeError(
            "未安装 Pillow，无法验证 GIF。请先运行: "
            "python -m pip install -r requirements.txt"
        )

    with Image.open(BytesIO(data)) as image:
        image.load()
        frames = getattr(image, "n_frames", 1)
        # 访问每一帧以尽早发现截断/损坏；不会把图片重新保存。
        for frame in range(frames):
            image.seek(frame)
            image.copy().load()
        return frames


def available_output_path(output_dir: Path, source_name: str) -> Path:
    source_path = Path(source_name)
    stem = source_path.stem or source_path.name or "marketface"
    candidate = output_dir / f"{stem}.gif"
    number = 1
    while candidate.exists():
        candidate = output_dir / f"{stem}_{number}.gif"
        number += 1
    return candidate


def iter_source_files(source_dir: Path, output_dir: Path):
    """Yield files under source_dir, excluding output_dir and its descendants."""
    output_resolved = output_dir.resolve()
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(output_resolved)
        except ValueError:
            yield path


def configure_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("qqnt_marketface_recover")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    return logger


def recover_directory(
    source_dir: Path,
    output_dir: Path,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> RecoverStats:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = configure_logger(output_dir / "recover.log")
    stats = RecoverStats()

    files = list(iter_source_files(source_dir, output_dir))
    total = len(files)

    def log(message: str, level: int = logging.INFO):
        logger.log(level, message)
        if on_log:
            on_log(message)

    log(f"开始扫描: {source_dir}")
    log(f"输出目录: {output_dir}")

    for number, source_path in enumerate(files, start=1):
        if cancel_event and cancel_event.is_set():
            log("用户取消处理。")
            break

        stats.scanned += 1
        display_name = str(source_path.relative_to(source_dir))
        if on_progress:
            on_progress(number, total, display_name)

        try:
            data = source_path.read_bytes()
            already_gif = is_gif_header(data)
            restored = data if already_gif else restore_marketface(data)

            if not is_gif_header(restored):
                stats.unknown += 1
                log(f"[无法识别] {display_name}")
                continue

            try:
                frame_count = validate_gif(restored)
            except Exception as exc:
                stats.unknown += 1
                log(f"[GIF验证失败] {display_name}: {exc}", logging.WARNING)
                continue

            destination = available_output_path(output_dir, source_path.name)
            destination.write_bytes(restored)

            if already_gif:
                stats.already_gif += 1
                action = "原本就是 GIF"
            else:
                stats.recovered += 1
                action = "恢复成功"

            if frame_count > 1:
                stats.animated += 1
                kind = f"动态, {frame_count} 帧"
            else:
                stats.static += 1
                kind = "静态"

            log(f"[{action}] {display_name} -> {destination.name} ({kind})")
        except Exception as exc:
            stats.errors += 1
            log(f"[处理异常] {display_name}: {exc}", logging.ERROR)
            logger.debug(traceback.format_exc())

    log(
        "完成: "
        f"Scanned: {stats.scanned}, "
        f"Already GIF: {stats.already_gif}, "
        f"Recovered: {stats.recovered}, "
        f"Animated: {stats.animated}, "
        f"Static: {stats.static}, "
        f"Unknown: {stats.unknown}, "
        f"Errors: {stats.errors}"
    )
    return stats


def format_summary(stats: RecoverStats) -> str:
    return (
        f"扫描文件数量: {stats.scanned}\n"
        f"原本就是 GIF: {stats.already_gif}\n"
        f"成功恢复 GIF: {stats.recovered}\n"
        f"动态 GIF: {stats.animated}\n"
        f"静态 GIF: {stats.static}\n"
        f"无法识别: {stats.unknown}\n"
        f"处理异常: {stats.errors}"
    )


def run_cli(source: Path, output: Optional[Path]) -> int:
    if not source.is_dir():
        print(f"源目录不存在或不是目录: {source}")
        return 2
    output = output or source / DEFAULT_OUTPUT_NAME
    stats = recover_directory(
        source,
        output,
        on_log=print,
        on_progress=lambda current, total, name: print(
            f"[{current}/{total}] {name}"
        ),
    )
    print("\n" + format_summary(stats))
    print(f"日志: {output.resolve() / 'recover.log'}")
    return 0


def start_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App:
        def __init__(self, root: tk.Tk):
            self.root = root
            self.root.title("QQNT 商城表情恢复工具")
            self.root.geometry("780x570")
            self.root.minsize(650, 450)
            self.cancel_event = threading.Event()
            self.worker = None

            outer = ttk.Frame(root, padding=12)
            outer.pack(fill="both", expand=True)

            ttk.Label(outer, text="源目录:").grid(row=0, column=0, sticky="w", pady=4)
            self.source_var = tk.StringVar()
            ttk.Entry(outer, textvariable=self.source_var).grid(
                row=0, column=1, sticky="ew", padx=6, pady=4
            )
            ttk.Button(outer, text="选择...", command=self.choose_source).grid(
                row=0, column=2, pady=4
            )

            ttk.Label(outer, text="输出目录:").grid(row=1, column=0, sticky="w", pady=4)
            self.output_var = tk.StringVar()
            ttk.Entry(outer, textvariable=self.output_var).grid(
                row=1, column=1, sticky="ew", padx=6, pady=4
            )
            ttk.Button(outer, text="选择...", command=self.choose_output).grid(
                row=1, column=2, pady=4
            )

            self.progress = ttk.Progressbar(outer, mode="determinate")
            self.progress.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 4))
            self.status_var = tk.StringVar(value="请选择源目录")
            ttk.Label(outer, textvariable=self.status_var).grid(
                row=3, column=0, columnspan=3, sticky="w", pady=4
            )

            buttons = ttk.Frame(outer)
            buttons.grid(row=4, column=0, columnspan=3, sticky="w", pady=8)
            self.start_button = ttk.Button(buttons, text="开始处理", command=self.start)
            self.start_button.pack(side="left")
            self.cancel_button = ttk.Button(
                buttons, text="取消", command=self.cancel, state="disabled"
            )
            self.cancel_button.pack(side="left", padx=8)

            ttk.Label(outer, text="运行日志:").grid(
                row=5, column=0, columnspan=3, sticky="w"
            )
            log_frame = ttk.Frame(outer)
            log_frame.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=4)
            self.log_text = tk.Text(log_frame, height=18, state="disabled", wrap="none")
            scrollbar = ttk.Scrollbar(
                log_frame, orient="vertical", command=self.log_text.yview
            )
            self.log_text.configure(yscrollcommand=scrollbar.set)
            self.log_text.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            outer.columnconfigure(1, weight=1)
            outer.rowconfigure(6, weight=1)

        def choose_source(self):
            selected = filedialog.askdirectory(title="选择 QQNT 缓存源目录")
            if selected:
                self.source_var.set(selected)
                if not self.output_var.get():
                    self.output_var.set(str(Path(selected) / DEFAULT_OUTPUT_NAME))

        def choose_output(self):
            selected = filedialog.askdirectory(title="选择输出目录")
            if selected:
                self.output_var.set(selected)

        def append_log(self, message: str):
            def update():
                self.log_text.configure(state="normal")
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            self.root.after(0, update)

        def update_progress(self, current: int, total: int, name: str):
            def update():
                self.progress["maximum"] = max(total, 1)
                self.progress["value"] = current
                self.status_var.set(f"正在处理 ({current}/{total}): {name}")
            self.root.after(0, update)

        def start(self):
            source = Path(self.source_var.get().strip())
            if not source.is_dir():
                messagebox.showerror("目录错误", "请选择有效的源目录。")
                return
            output_text = self.output_var.get().strip()
            output = Path(output_text) if output_text else source / DEFAULT_OUTPUT_NAME
            if source.resolve() == output.resolve():
                messagebox.showerror("目录错误", "输出目录不能与源目录相同。")
                return

            self.cancel_event.clear()
            self.start_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self.progress["value"] = 0
            self.append_log("=" * 60)
            self.worker = threading.Thread(
                target=self.run_worker, args=(source, output), daemon=True
            )
            self.worker.start()

        def cancel(self):
            self.cancel_event.set()
            self.status_var.set("正在取消，当前文件处理结束后停止...")

        def run_worker(self, source: Path, output: Path):
            stats = recover_directory(
                source,
                output,
                on_log=self.append_log,
                on_progress=self.update_progress,
                cancel_event=self.cancel_event,
            )

            def finished():
                self.start_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                self.status_var.set("处理完成" if not self.cancel_event.is_set() else "已取消")
                messagebox.showinfo("处理结果", format_summary(stats))

            self.root.after(0, finished)

    root = tk.Tk()
    App(root)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="QQNT 商城/市场表情批量恢复工具")
    parser.add_argument("source", nargs="?", type=Path, help="源目录；不填写则启动 GUI")
    parser.add_argument("-o", "--output", type=Path, help="输出目录，默认是源目录/output")
    args = parser.parse_args()

    if args.source:
        raise SystemExit(run_cli(args.source, args.output))
    start_gui()


if __name__ == "__main__":
    main()
