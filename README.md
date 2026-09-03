# QQNT 商城/市场表情批量恢复工具

用于恢复 QQNT 商城/市场缓存中的表情文件。工具按照已确认的规则恢复原始 GIF 字节，不重新编码图片。

## 功能

- 递归扫描源目录中的所有文件，不依赖扩展名。
- 自动识别原本就是 `GIF87a` / `GIF89a` 的文件。
- 对其他文件应用 QQNT 规则：
  - 每 50 字节为周期；
  - 周期内前 20 字节执行 `byte ^ 0xFF`；
  - 后 30 字节保持原样。
- 仅当恢复结果为有效 GIF 时输出。
- 使用 Pillow 在内存中验证 GIF，不重新保存图片。
- 统计动态 GIF、静态 GIF、无法识别文件和处理异常。
- 源文件只读，输出写入独立目录。
- 支持图形界面和命令行。

## 安装

Windows 上安装 Python 3.9 或更高版本，然后在本目录执行：

```bat
python -m pip install -r requirements.txt
```

如果系统中有多个 Python，也可以使用：

```bat
py -m pip install -r requirements.txt
```

## 启动 GUI

```bat
python qqnt_marketface_recover.py
```

不提供源目录参数时会启动 GUI。选择源目录后，输出目录默认是：

```text
源目录\output
```

点击“开始处理”即可批量恢复。

## 命令行用法

使用默认输出目录：

```bat
python qqnt_marketface_recover.py "D:\path\to\qq-cache"
```

指定输出目录：

```bat
python qqnt_marketface_recover.py "D:\path\to\qq-cache" -o "D:\path\to\recovered"
```

## 输出与日志

成功文件会保存为 `.gif`：

- 无扩展名源文件：`文件名.gif`
- 有扩展名源文件：使用原文件名主体并改为 `.gif`
- 输出文件重名时：自动使用 `_1`、`_2` 等序号
- 已存在的输出文件不会覆盖

日志文件：

```text
输出目录\recover.log
```

## 统计项

任务完成后会显示：

- 扫描文件数量
- 原本就是 GIF 的数量
- 成功恢复 GIF 的数量
- 动态 GIF 数量
- 静态 GIF 数量
- 无法识别数量
- 处理异常数量

## 安全说明

- 不修改源文件。
- 不删除源文件。
- 不覆盖源文件。
- 默认输出到源目录下的独立 `output` 目录。
- 扫描时会自动排除输出目录，避免重复处理生成结果。
- 某个文件读取失败或验证失败时，会记录日志并继续处理其他文件。

## 打包为 EXE（可选）

安装 PyInstaller：

```bat
python -m pip install pyinstaller
```

构建无控制台窗口的 GUI 程序：

```bat
pyinstaller --onefile --windowed --name QQNTMarketFaceRecover qqnt_marketface_recover.py
```

生成的 EXE 位于：

```text
dist\QQNTMarketFaceRecover.exe
```

打包后的程序仍然只读取源目录，并将恢复文件写入用户选择的输出目录。
