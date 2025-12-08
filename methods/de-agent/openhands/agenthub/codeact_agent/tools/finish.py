from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
import os
from openhands.llm.tool_names import FINISH_TOOL_NAME

_DESC_ZH = """最终报告提交工具（Final Report Submission Tool）。
- message 参数必须包含 `/workspace/result.md` 中的完整报告全文，且以【回复用户】开头。
- 调用本工具前必须已将报告写入该文件，不得包含未来承诺措辞。
"""
_DESC_EN = """Final Report Submission Tool.
- The message must contain the full report text read from `/workspace/result.md`, starting with 【回复用户】.
- Before calling this tool, you must have written the report to that file; no future promises allowed.
"""

def create_finish_tool(lang: str | None = None) -> ChatCompletionToolParam:
    lang = (lang or os.getenv("DATAAGENT_PROMPT_LANG", "zh")).lower()
    desc = _DESC_EN if lang == "en" else _DESC_ZH
    return ChatCompletionToolParam(
        type="function",
        function=ChatCompletionToolParamFunctionChunk(
            name=FINISH_TOOL_NAME,
            description=desc,
            parameters={
                "type": "object",
                "required": ["message"],
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            "Full final report (Markdown, self-contained; must start with 【回复用户】; no future promises)."
                            if lang == "en"
                            else "最终分析报告全文（Markdown，自包含；以【回复用户】开头；不得包含未来承诺措辞）。"
                        ),
                    }
                },
                "additionalProperties": False,
            },
        ),
    )

FinishTool = create_finish_tool()
