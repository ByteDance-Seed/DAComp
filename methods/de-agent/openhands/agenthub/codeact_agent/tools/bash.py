from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
import os
from openhands.agenthub.codeact_agent.tools.prompt import refine_prompt
from openhands.llm.tool_names import EXECUTE_BASH_TOOL_NAME

_DETAILED_BASH_DESCRIPTION_EN = """Execute a bash command in the terminal within a persistent shell session.


### Command Execution
* One command at a time: You can only execute one bash command at a time. If you need to run multiple commands sequentially, use `&&` or `;` to chain them together.
* Persistent session: Commands execute in a persistent shell session where environment variables, virtual environments, and working directory persist between commands.
* Soft timeout: Commands have a soft timeout of 10 seconds, once that's reached, you have the option to continue or interrupt the command (see section below for details)

### Long-running Commands
* For commands that may run indefinitely, run them in the background and redirect output to a file, e.g. `python3 app.py > server.log 2>&1 &`.
* For commands that may run for a long time (e.g. installation or testing commands), or commands that run for a fixed amount of time (e.g. sleep), you should set the "timeout" parameter of your function call to an appropriate value.
* If a bash command returns exit code `-1`, this means the process hit the soft timeout and is not yet finished. By setting `is_input` to `true`, you can:
  - Send empty `command` to retrieve additional logs
  - Send text (set `command` to the text) to STDIN of the running process
  - Send control commands like `C-c` (Ctrl+C), `C-d` (Ctrl+D), or `C-z` (Ctrl+Z) to interrupt the process
  - If you do C-c, you can re-start the process with a longer "timeout" parameter to let it run to completion

### Best Practices
* Directory verification: Before creating new directories or files, first verify the parent directory exists and is the correct location.
* Directory management: Try to maintain working directory by using absolute paths and avoiding excessive use of `cd`.

### Output Handling
* Output truncation: If the output exceeds a maximum length, it will be truncated before being returned.
"""

_SHORT_BASH_DESCRIPTION_EN = """Execute a bash command in the terminal.
* Long running commands: For commands that may run indefinitely, it should be run in the background and the output should be redirected to a file, e.g. command = `python3 app.py > server.log 2>&1 &`. For commands that need to run for a specific duration, you can set the "timeout" argument to specify a hard timeout in seconds.
* Interact with running process: If a bash command returns exit code `-1`, this means the process is not yet finished. By setting `is_input` to `true`, the assistant can interact with the running process and send empty `command` to retrieve any additional logs, or send additional text (set `command` to the text) to STDIN of the running process, or send command like `C-c` (Ctrl+C), `C-d` (Ctrl+D), `C-z` (Ctrl+Z) to interrupt the process.
* One command at a time: You can only execute one bash command at a time. If you need to run multiple commands sequentially, you can use `&&` or `;` to chain them together."""


_DETAILED_BASH_DESCRIPTION = """在终端中持久化 Shell 会话中执行 bash 命令。

### 命令执行
* 一次执行一个命令：您一次只能执行一个 bash 命令。如果您需要连续运行多个命令，请使用 `&&` 或 `;` 将它们串联起来。
* 持久化会话：命令在持久化 Shell 会话中执行，环境变量、虚拟环境和工作目录在命令之间保持不变。
* 软超时：命令的软超时时间为 10 秒，一旦达到该超时时间，您可以选择继续或中断命令（详情请参阅下文）。

### 长时间运行的命令
* 对于可能无限期运行的命令，请在后台运行它们并将输出重定向到文件，例如 `python3 app.py > server.log 2>&1 &`。
* 对于可能长时间运行的命令（例如安装或测试命令），或运行时间固定的命令（例如 sleep），您应该将函数调用的“timeout”参数设置为合适的值。
* 如果 bash 命令返回退出代码“-1”，则表示进程已达到软超时，尚未完成。通过将“is_input”设置为“true”，您可以：
- 发送空的“command”以检索其他日志
- 向正在运行的进程的标准输入 (STDIN) 发送文本（将“command”设置为文本）
- 发送控制命令，例如“C-c”（Ctrl+C）、“C-d”（Ctrl+D）或“C-z”（Ctrl+Z）以中断进程
- 如果您执行的是“C-c”，则可以使用更长的“timeout”参数重新启动进程，使其运行完成

### 最佳实践
* 目录验证：在创建新目录或文件之前，首先验证父目录是否存在且位置正确。
* 目录管理：尽量使用绝对路径并避免过度使用“cd”命令来维护工作目录。

### 输出处理
* 输出截断：如果输出超过最大长度，则会在返回前被截断。
"""

_SHORT_BASH_DESCRIPTION = """在终端中执行 bash 命令。
* 长时间运行的命令：对于可能无限期运行的命令，应在后台运行，并将输出重定向到文件，例如 command = `python3 app.py > server.log 2>&1 &`。对于需要运行特定时长的命令，您可以设置“timeout”参数以指定硬超时（以秒为单位）。
* 与正在运行的进程交互：如果 bash 命令返回退出代码 `-1`，则表示该进程尚未完成。通过将 `is_input` 设置为 `true`，助手可以与正在运行的进程交互并发送空的 `command` 来检索任何其他日志，或向正在运行的进程的标准输入 (STDIN) 发送其他文本（将 `command` 设置为文本），或者发送类似 `C-c` (Ctrl+C)、`C-d` 的命令(Ctrl+D)、`C-z` (Ctrl+Z) 中断进程。
* 一次执行一个命令：您一次只能执行一个 bash 命令。如果需要按顺序运行多个命令，可以使用 `&&` 或 `;` 将它们链接在一起。"""


def create_cmd_run_tool(
    use_short_description: bool = False,
    lang: str | None = None,
) -> ChatCompletionToolParam:
    lang = (lang or os.getenv("DATAAGENT_PROMPT_LANG", "zh")).lower()
    if lang == "en":
        desc = _SHORT_BASH_DESCRIPTION_EN  if use_short_description else _DETAILED_BASH_DESCRIPTION_EN
        cmd_desc = (
            "The bash command to execute. Empty string fetches more logs when the previous exit code is -1. "
            "Use C-c to interrupt. One command at a time; chain with && or ; if needed."
        )
        is_input_desc = (
            "If true, the command is input to the running process; otherwise it is a terminal command."
        )
        timeout_desc = "Optional hard timeout (seconds)."
    else:
        desc = _SHORT_BASH_DESCRIPTION if use_short_description else _DETAILED_BASH_DESCRIPTION
        cmd_desc = (
            "要执行的 bash 命令。如果先前退出码为 -1，可输入空字符串查看更多日志；可用 C-c 中断。"
            "一次只能执行一个命令；需串联用 && 或 ;。"
        )
        is_input_desc = "若为 True，此命令作为正在运行进程的输入；否则在终端中执行。"
        timeout_desc = "可选。命令执行的硬超时（秒）。"

    return ChatCompletionToolParam(
        type="function",
        function=ChatCompletionToolParamFunctionChunk(
            name=EXECUTE_BASH_TOOL_NAME,
            description=refine_prompt(desc),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": refine_prompt(cmd_desc)},
                    "is_input": {
                        "type": "string",
                        "description": refine_prompt(is_input_desc),
                        "enum": ["true", "false"],
                    },
                    "timeout": {"type": "number", "description": refine_prompt(timeout_desc)},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        ),
    )
