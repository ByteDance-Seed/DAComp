from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
import os

_DESC_ZH = """在 IPython 环境中运行 Python 代码单元。
* 在使用变量之前定义变量并导入包。
* 在 IPython 中定义的变量在其外部不可用。
"""
_DESC_EN = """Run a cell of Python code in an IPython environment.
* Define variables and import packages before using them.
* Variables defined in IPython are not available outside it.
"""

def create_ipython_tool(lang: str | None = None) -> ChatCompletionToolParam:
    lang = (lang or os.getenv("DATAAGENT_PROMPT_LANG", "zh")).lower()
    desc = _DESC_EN if lang == "en" else _DESC_ZH
    return ChatCompletionToolParam(
        type='function',
        function=ChatCompletionToolParamFunctionChunk(
            name='execute_ipython_cell',
            description=desc,
            parameters={
                'type': 'object',
                'properties': {
                    'code': {
                        'type': 'string',
                        'description': 'The Python code to execute. Supports magic commands like %pip.'
                        if lang == 'en' else '要执行的 Python 代码。支持 %pip 之类的魔法命令。',
                    },
                },
                'required': ['code'],
            },
        ),
    )

IPythonTool = create_ipython_tool()
