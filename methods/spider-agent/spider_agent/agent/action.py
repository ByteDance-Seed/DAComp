#coding=utf8
import json
import re
from dataclasses import dataclass, field
from typing import Optional, Any, Union, List, Dict
from abc import ABC

def remove_quote(text: str) -> str:
    """ 
    If the text is wrapped by a pair of quote symbols, remove them.
    In the middle of the text, the same quote symbol should remove the '/' escape character.
    """
    for quote in ['"', "'", "`"]:
        if text.startswith(quote) and text.endswith(quote):
            text = text[1:-1]
            text = text.replace(f"\\{quote}", quote)
            break
    return text.strip()


@dataclass
class Action(ABC):
    
    action_type: str = field(
        repr=False,
        metadata={"help": 'type of action, e.g. "exec_code", "create_file", "terminate"'}
    )


    @classmethod
    def get_action_description(cls) -> str:
        return """
Action: action format
Description: detailed definition of this action type.
Usage: example cases
Observation: the observation space of this action type.
"""

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Any]:
        raise NotImplementedError

@dataclass
class Bash(Action):

    action_type: str = field(
        default="exec_code",
        init=False,
        repr=False,
        metadata={"help": 'type of action, c.f., "exec_code"'}
    )

    code: str = field(
        metadata={"help": 'command to execute'}
    )

    @classmethod
    def get_action_description(cls) -> str:
        return """
## Bash Action
* Signature: Bash(code="shell_command")
* Description: This action string will execute a valid shell command in the `code` field. Only non-interactive commands are supported. Commands like "vim" and viewing images directly (e.g., using "display") are not allowed. Please use python3, do not use python.
* Example: Bash(code="ls -l")
* Example: Bash(code="python3 xxx.py")
"""

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        # Multiple patterns to handle different quote styles and escaping
        patterns = [
            # Original patterns with better escaping support
            r'Bash\(code="((?:\\.|[^"\\])*)"\)',  # Original pattern
            r"Bash\(code='((?:\\.|[^'\\])*)'\)",  # Single quotes
            r'Bash\(code="""(.*?)"""\)',          # Triple double quotes
            r"Bash\(code='''(.*?)'''\)",          # Triple single quotes
            r'Bash\(code=`(.*?)`\)',              # Backticks
            
            # More flexible patterns with optional spaces
            r'Bash\(\s*code\s*=\s*"((?:\\.|[^"\\])*)"\s*\)',  # Spaces around equals
            r"Bash\(\s*code\s*=\s*'((?:\\.|[^'\\])*)'\s*\)",  # Spaces around equals single quotes
            r'Bash\(\s*code\s*=\s*"""(.*?)"""\s*\)',          # Spaces around equals triple quotes
            r"Bash\(\s*code\s*=\s*'''(.*?)'''\s*\)",          # Spaces around equals triple single quotes
            
            # Patterns without the code= prefix (sometimes LLMs forget this)
            r'Bash\("((?:\\.|[^"\\])*)"\)',       # Direct string in double quotes
            r"Bash\('((?:\\.|[^'\\])*)'\)",       # Direct string in single quotes  
            r'Bash\("""(.*?)"""\)',               # Direct string in triple double quotes
            r"Bash\('''(.*?)'''\)",               # Direct string in triple single quotes
            
            # Handle incomplete quotes or missing closing quotes
            r'Bash\(code="((?:\\.|[^"\\])*)',     # Missing closing double quote
            r"Bash\(code='((?:\\.|[^'\\])*)",     # Missing closing single quote
            r'Bash\(code="""(.*?)',               # Missing closing triple double quote
            r"Bash\(code='''(.*?)",               # Missing closing triple single quote
            
            # Handle missing parentheses
            r'Bash\(code="((?:\\.|[^"\\])*)"[^)]*', # Missing closing parenthesis
            r"Bash\(code='((?:\\.|[^'\\])*)'[^)]*", # Missing closing parenthesis single quote
            
            # Handle malformed syntax but still extractable
            r'Bash[^(]*\(.*?code[^=]*=[^"\'`]*["\'`]([^"\'`]+)',  # Very flexible fallback
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, flags=re.DOTALL)
            if matches:
                code = matches[-1]
                if isinstance(code, tuple):
                    code = code[0]  # Handle tuple matches
                # Clean and process the code
                processed_code = cls.remove_quote(code.strip())
                if processed_code:  # Only return if we have actual code
                    return cls(code=processed_code)
        
        # Try even more flexible parsing for edge cases
        flexible_patterns = [
            # Look for Bash followed by any content that looks like a command
            r'Bash\([^)]*["\']([^"\']+)["\'][^)]*\)',
            # Look for Bash with code parameter anywhere
            r'Bash\([^)]*code[^)]*?["\']([^"\']+)["\'][^)]*\)',
            # Very loose pattern - any Bash with quoted content
            r'Bash[^(]*\([^)]*["\']([^"\']{3,})["\'][^)]*\)',
        ]
        
        for pattern in flexible_patterns:
            matches = re.findall(pattern, text, flags=re.DOTALL | re.IGNORECASE)
            if matches:
                code = matches[-1]
                if isinstance(code, tuple):
                    code = code[0]
                # More aggressive cleaning for flexible matches
                processed_code = cls.remove_quote(code.strip())
                # Basic validation - should look like a command
                if processed_code and (
                    ' ' in processed_code or  # Multi-word command
                    any(cmd in processed_code.lower() for cmd in ['ls', 'cd', 'pwd', 'cat', 'echo', 'mkdir', 'cp', 'mv', 'rm', 'grep', 'find', 'python', 'python3', 'pip', 'npm', 'git', 'docker']) or
                    processed_code.count('/') > 0 or  # Contains path
                    processed_code.count('.') > 0     # Contains file extension or command with dots
                ):
                    return cls(code=processed_code)
        
        # Last resort: look for any reasonable command-like string after "Bash"
        last_resort_match = re.search(r'Bash[^a-zA-Z0-9_][^)]*?([a-zA-Z][a-zA-Z0-9_/.\s-]{2,})', text)
        if last_resort_match:
            potential_code = last_resort_match.group(1).strip()
            # Clean up potential artifacts
            potential_code = re.sub(r'^[^a-zA-Z0-9/]*', '', potential_code)  # Remove leading non-alphanumeric
            potential_code = re.sub(r'[^a-zA-Z0-9/.\s-]*$', '', potential_code)  # Remove trailing artifacts
            if len(potential_code) >= 2 and any(c.isalpha() for c in potential_code):
                return cls(code=potential_code)
        
        return None

    @staticmethod
    def remove_quote(s: str) -> str:
        """
        Convert common escape sequences (e.g., \\n, \\t) while preserving non-ASCII characters.
        Using unicode_escape on the whole string corrupts UTF-8 payloads, so we only translate
        a small, safe subset of escapes needed for commands.
        """
        replacements = [
            (r'\\n', '\n'),
            (r'\\t', '\t'),
            (r'\\r', '\r'),
            (r'\\"', '"'),
            (r"\\'", "'"),
            (r'\\\\', '\\'),
        ]
        for src, dst in replacements:
            s = s.replace(src, dst)
        return s
    
    def __repr__(self) -> str:
        formatted_code = json.dumps(self.code, ensure_ascii=False)
        return f'{self.__class__.__name__}(code={formatted_code})'
    
    

@dataclass
class CreateFile(Action):

    action_type: str = field(
        default="create_file",
        init=False,
        repr=False,
        metadata={"help": 'type of action, c.f., "create_file"'}
    )

    code: str = field(
        metadata={"help": 'code to write into file'}
    )

    filepath: Optional[str] = field(
        default=None,
        metadata={"help": 'name of file to create'}
    )

    def __repr__(self) -> str:
        filepath = self.filepath or ""
        formatted_path = json.dumps(filepath, ensure_ascii=False)
        code_text = self.code.rstrip()
        return f"CreateFile(filepath={formatted_path}):\n```\n{code_text}\n```"

    @classmethod
    def get_action_description(cls) -> str:
        return """
## CreateFile
Signature: CreateFile(filepath="path/to/file"):
```
file_content
```
Description: This action will create a file in the field `filepath` with the content wrapped by paired ``` symbols. Make sure the file content is complete and correct. If the file already exists, you can only use EditFile to modify it.
Example: CreateFile(filepath="hello_world.py"):
```
print("Hello, world!")
```
"""

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        # 先尝试匹配带content参数的格式
        content_patterns = [
            r'CreateFile\(filepath=(.*?),\s*content=(.*?)\)',
            r'CreateFile\(filepath=(.*?)\s*,\s*content=(.*?)\)',
        ]
        
        for pattern in content_patterns:
            matches = re.findall(pattern, text, flags=re.DOTALL)
            if matches:
                filepath, content = matches[-1]
                filepath = remove_quote(filepath.strip())
                content = remove_quote(content.strip())
                return cls(code=content, filepath=filepath)
        
        # 然后尝试标准的filepath + 代码块格式
        patterns = [
            # Pattern 1: 最常见格式 - 引号filepath，冒号后换行，然后代码块（改进版）
            r'CreateFile\(filepath="([^"]+)"\)\s*:\s*\n```\n(.*?)\n```',
            r'CreateFile\(filepath="([^"]+)"\)\s*:\s*\n```(?:\w+)?\n(.*?)\n```',
            
            # Pattern 2: 引号filepath，冒号后直接代码块
            r'CreateFile\(filepath="([^"]+)"\)\s*:\s*```\n(.*?)```',
            r'CreateFile\(filepath="([^"]+)"\)\s*:\s*```(?:\w+)?\s*(.*?)```',
            
            # Pattern 3: 单引号filepath版本
            r'CreateFile\(filepath=\'([^\']+)\'\)\s*:\s*\n```\n(.*?)\n```',
            r'CreateFile\(filepath=\'([^\']+)\'\)\s*:\s*\n```(?:\w+)?\n(.*?)\n```',
            
            # Pattern 4: 无引号或可选引号版本
            r'CreateFile\(filepath=([^)]+)\)\s*:\s*\n```\n(.*?)\n```',
            r'CreateFile\(filepath=([^)]+)\)\s*:\s*\n```(?:\w+)?\n(.*?)\n```',
            
            # Pattern 5: 更宽松的匹配（处理各种空白字符）
            r'CreateFile\(filepath=["\']?([^"\')\s]+)["\']?\)\s*:\s*\n\s*```[^\n]*\n(.*?)\n\s*```',
            
            # Pattern 6: 无冒号格式
            r'CreateFile\(filepath=["\']?([^"\')\s]+)["\']?\)\s*\n```\n(.*?)\n```',
            r'CreateFile\(filepath=["\']?([^"\')\s]+)["\']?\)\s*```\n(.*?)```',
            
            # Pattern 7: 三引号格式
            r'CreateFile\(filepath=["\']?([^"\')\s]+)["\']?\)\s*:\s*\'\'\'(.*?)\'\'\'',
            
            # Pattern 8: 最宽松的格式（最后的fallback）
            r'CreateFile\(filepath=["\']?(.*?)["\']?\).*?```[^\n]*\n(.*?)```',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if matches:
                match = matches[-1]
                if isinstance(match, tuple) and len(match) >= 2:
                    filepath = match[0].strip()
                    code = match[1].strip() if len(match) > 1 and match[1] else ""
                        
                    if filepath and code:
                        # 清理filepath中可能残留的引号
                        filepath = remove_quote(filepath)
                        return cls(code=code, filepath=filepath)
        
        # 如果以上都不匹配，尝试一个更简单直接的方法
        # 查找CreateFile(filepath=...)后面最近的代码块
        simple_match = re.search(
            r'CreateFile\(filepath=([^)]+)\)[^\n]*\n\s*```[^\n]*\n(.*?)\n\s*```',
            text,
            flags=re.DOTALL | re.MULTILINE
        )
        if simple_match:
            filepath = remove_quote(simple_match.group(1).strip())
            code = simple_match.group(2).strip()
            if filepath and code:
                return cls(code=code, filepath=filepath)
        
        # 处理缺少结束```的情况 - 修复agents.py提取动作字符串时截断的问题
        incomplete_patterns = [
            # 双引号版本
            r'CreateFile\(filepath="([^"]+)"\)\s*:\s*\n```[^\n]*\n(.*)',
            # 单引号版本 - 这是缺少的关键模式！
            r'CreateFile\(filepath=\'([^\']+)\'\)\s*:\s*\n```[^\n]*\n(.*)',
            # 缺少右括号的版本 - 语法错误但需要容错
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n```[^\n]*\n(.*)',
            r'CreateFile\(filepath=\'([^\']+)\'\s*:\s*\n```[^\n]*\n(.*)',
        ]
        
        for pattern in incomplete_patterns:
            incomplete_match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if incomplete_match:
                filepath = incomplete_match.group(1).strip()
                code = incomplete_match.group(2).strip()
                # 清理代码中可能包含的尾部```标记
                code = re.sub(r'\n```\s*$', '', code)
                if filepath:  # 允许空代码
                    return cls(code=code, filepath=filepath)
        
        # 处理单引号和三引号格式 - 如 CreateFile(filepath='...':'''...''')
        triple_quote_patterns = [
            # 完整的三引号格式 - 双引号版本
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*?)\n\'\'\'\s*\)',
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\'\'\'\s*\n(.*?)\n\'\'\'\s*\)',
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*(.*?)\s*\'\'\'\s*\)',
            # 完整的三引号格式 - 单引号版本
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*?)\n'''\s*\)",
            r"CreateFile\(filepath='([^']+)'\s*:\s*'''\s*\n(.*?)\n'''\s*\)",
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n'''\s*(.*?)\s*'''\s*\)",
            # 缺少结束三引号的格式 - 双引号版本
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*)',
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\'\'\'\s*\n(.*)',
            # 缺少结束三引号的格式 - 单引号版本
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*)",
            r"CreateFile\(filepath='([^']+)'\s*:\s*'''\s*\n(.*)",
            # 缺少右括号 + 三引号格式 - 双引号版本
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*?)\n\'\'\'\s*\)',
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\'\'\'\s*\n(.*?)\n\'\'\'\s*\)',
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*(.*?)\s*\'\'\'\s*\)',
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*)',
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\'\'\'\s*\n(.*)',
            # 缺少右括号 + 三引号格式 - 单引号版本
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*?)\n'''\s*\)",
            r"CreateFile\(filepath='([^']+)'\s*:\s*'''\s*\n(.*?)\n'''\s*\)",
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n'''\s*(.*?)\s*'''\s*\)",
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*)",
            r"CreateFile\(filepath='([^']+)'\s*:\s*'''\s*\n(.*)",
        ]
        
        for pattern in triple_quote_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                code = match.group(2).strip() if len(match.groups()) >= 2 else ""
                # 清理代码中可能包含的尾部'''标记
                code = re.sub(r'\n\'\'\'\s*$', '', code)
                if filepath:  # 允许空代码
                    return cls(code=code, filepath=filepath)
        
        # 处理更宽松的参数格式，包括额外的空格
        flexible_patterns = [
            # 参数周围有额外空格的情况
            r'CreateFile\(\s*filepath\s*=\s*"([^"]+)"\s*\)\s*:\s*\n```[^\n]*\n(.*?)```',
            r"CreateFile\(\s*filepath\s*=\s*'([^']+)'\s*\)\s*:\s*\n```[^\n]*\n(.*?)```",
            r'CreateFile\(\s*filepath\s*=\s*"([^"]+)"\s*\)\s*:\s*\n```[^\n]*\n(.*)',
            r"CreateFile\(\s*filepath\s*=\s*'([^']+)'\s*\)\s*:\s*\n```[^\n]*\n(.*)",
            # 混合引号的情况（虽然语法错误，但容错处理）
            r'CreateFile\(filepath="([^"\']+)["\']?\s*:\s*\n```[^\n]*\n(.*)',
            r"CreateFile\(filepath='([^\"']+)[\"']?\s*:\s*\n```[^\n]*\n(.*)",
            # 空内容的特殊处理
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n```\s*\n\s*```',
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n```\s*\n\s*```",
            # 处理标准三引号但缺少右括号的情况
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*?)\n\'\'\'\s*',
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*?)\n'''\s*",
        ]
        
        for pattern in flexible_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                # 清理 filepath 中的混合引号问题
                filepath = re.sub(r'["\']$', '', filepath)  # 移除尾部的引号
                if len(match.groups()) >= 2 and match.group(2):
                    code = match.group(2).strip()
                    # 清理代码中可能的标记
                    code = re.sub(r'^```\s*$', '', code)  # 移除只有```的行
                    code = re.sub(r'^\s*```\s*\n?', '', code)  # 移除开头的```
                    code = re.sub(r'\n\s*```\s*$', '', code)  # 移除结尾的```
                else:
                    code = ""  # 处理空内容的情况
                if filepath:  # 即使代码为空也允许
                    return cls(code=code, filepath=filepath)
        
        # 处理空代码块的特殊情况
        empty_block_patterns = [
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n```\s*\n\s*```\s*',
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n```\s*\n\s*```\s*",
            r'CreateFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n\s*\'\'\'\s*',
            r"CreateFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n\s*'''\s*",
        ]
        
        for pattern in empty_block_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                if filepath:
                    return cls(code="", filepath=filepath)
        
        # 处理混合引号的特殊情况 
        mixed_quote_patterns = [
            # 双引号开头，单引号结尾的错误格式
            r'CreateFile\(filepath="([^"\']*)\'\s*:\s*\n```[^\n]*\n(.*?)```',
            r'CreateFile\(filepath="([^"\']*)\'\s*:\s*\n```[^\n]*\n(.*)',
            # 单引号开头，双引号结尾的错误格式
            r"CreateFile\(filepath='([^\"']*)\"\s*:\s*\n```[^\n]*\n(.*?)```",
            r"CreateFile\(filepath='([^\"']*)\"\s*:\s*\n```[^\n]*\n(.*)",
        ]
        
        for pattern in mixed_quote_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                code = match.group(2).strip() if len(match.groups()) >= 2 else ""
                # 对于混合引号，保持原始的文件路径（包括错误的引号）
                if filepath:
                    return cls(code=code, filepath=filepath + "'")  # 添加丢失的单引号
        
        # 最后的容错模式 - 尝试匹配任何包含CreateFile的内容
        final_fallback_patterns = [
            # 匹配任何形式的CreateFile，无论语法多么错误
            r'CreateFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^)]*\).*?```[^\n]*\n(.*?)```',
            r'CreateFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^)]*\).*?```[^\n]*\n(.*)',
            r'CreateFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^)]*\).*?\'\'\'\s*\n(.*?)\'\'\'\s*',
            r'CreateFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^)]*\).*?\'\'\'\s*\n(.*)',
            # 处理所有可能的语法错误和缺失
            r'CreateFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^):]*[:)]?\s*[^`\']*[`\']{3}[^\n]*\n(.*)',
        ]
        
        for pattern in final_fallback_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                code = match.group(2).strip() if len(match.groups()) >= 2 else ""
                # 清理代码中的尾部标记
                code = re.sub(r'\n[`\']{3,}\s*$', '', code)
                # 清理开头的多余标记
                code = re.sub(r'^[`\']{3,}[^\n]*\n', '', code) 
                if filepath:
                    return cls(code=code, filepath=filepath)
        
        return None
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(filepath='{self.filepath}':\n'''\n{self.code}\n''')"
       
@dataclass
class EditFile(Action):
    action_type: str = field(default="edit_file",init=False,repr=False,metadata={"help": 'type of action, c.f., "edit_file"'})

    code: str = field(metadata={"help": 'code to write into file'})

    filepath: Optional[str] = field(default=None,metadata={"help": 'name of file to edit'})

    def __repr__(self) -> str:
        return f"EditFile(filepath=\"{self.filepath}\"):\n```\n{self.code.strip()}\n```"

    @classmethod
    def get_action_description(cls) -> str:
        return """
## EditFile
Signature: EditFile(filepath="path/to/file"):
```
file_content
```
Description: This action will overwrite the file specified in the filepath field with the content wrapped in paired ``` symbols. Normally, you need to read the file before deciding to use EditFile to modify it.
Example: EditFile(filepath="hello_world.py"):
```
print("Hello, world!")
```
"""

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        # 先尝试匹配带content参数的格式
        content_patterns = [
            r'EditFile\(filepath=(.*?),\s*content=(.*?)\)',
            r'EditFile\(filepath=(.*?)\s*,\s*content=(.*?)\)',
        ]
        
        for pattern in content_patterns:
            matches = re.findall(pattern, text, flags=re.DOTALL)
            if matches:
                filepath, content = matches[-1]
                filepath = remove_quote(filepath.strip())
                content = remove_quote(content.strip())
                return cls(code=content, filepath=filepath)
        
        # 然后尝试标准的filepath + 代码块格式
        patterns = [
            # Pattern 1: 最常见格式 - 引号filepath，冒号后换行，然后代码块
            r'EditFile\(filepath="([^"]+)"\)\s*:\s*\n```\n(.*?)\n```',
            r'EditFile\(filepath="([^"]+)"\)\s*:\s*\n```(?:\w+)?\n(.*?)\n```',
            
            # Pattern 2: 引号filepath，冒号后直接代码块
            r'EditFile\(filepath="([^"]+)"\)\s*:\s*```\n(.*?)```',
            r'EditFile\(filepath="([^"]+)"\)\s*:\s*```(?:\w+)?\s*(.*?)```',
            
            # Pattern 3: 单引号filepath版本
            r'EditFile\(filepath=\'([^\']+)\'\)\s*:\s*\n```\n(.*?)\n```',
            r'EditFile\(filepath=\'([^\']+)\'\)\s*:\s*\n```(?:\w+)?\n(.*?)\n```',
            
            # Pattern 4: 无引号或可选引号版本
            r'EditFile\(filepath=([^)]+)\)\s*:\s*\n```\n(.*?)\n```',
            r'EditFile\(filepath=([^)]+)\)\s*:\s*\n```(?:\w+)?\n(.*?)\n```',
            
            # Pattern 5: 更宽松的匹配（处理各种空白字符）
            r'EditFile\(filepath=["\']?([^"\')\s]+)["\']?\)\s*:\s*\n\s*```[^\n]*\n(.*?)\n\s*```',
            
            # Pattern 6: 无冒号格式
            r'EditFile\(filepath=["\']?([^"\')\s]+)["\']?\)\s*\n```\n(.*?)\n```',
            r'EditFile\(filepath=["\']?([^"\')\s]+)["\']?\)\s*```\n(.*?)```',
            
            # Pattern 7: 原有的匹配模式（保持向后兼容）
            r'EditFile\(filepath=(.*?)\).*?```[ \t]*(\w+)?[ \t]*\r?\n(.*)[\r\n \t]*```',
            
            # Pattern 8: 最宽松的格式（最后的fallback）
            r'EditFile\(filepath=["\']?(.*?)["\']?\).*?```[^\n]*\n(.*?)```',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if matches:
                match = matches[-1]
                if isinstance(match, tuple) and len(match) >= 2:
                    filepath = match[0].strip()
                    # 处理原有格式（有3个组的情况）
                    if len(match) == 3 and match[1] and not match[2]:
                        code = match[1].strip() if match[1] else ""
                    else:
                        code = match[-1].strip() if match[-1] else ""
                        
                    if filepath and code:
                        # 清理filepath中可能残留的引号
                        filepath = remove_quote(filepath)
                        return cls(code=code, filepath=filepath)
        
        # 如果以上都不匹配，尝试一个更简单直接的方法
        # 查找EditFile(filepath=...)后面最近的代码块
        simple_match = re.search(
            r'EditFile\(filepath=([^)]+)\)[^\n]*\n\s*```[^\n]*\n(.*?)\n\s*```',
            text,
            flags=re.DOTALL | re.MULTILINE
        )
        if simple_match:
            filepath = remove_quote(simple_match.group(1).strip())
            code = simple_match.group(2).strip()
            if filepath and code:
                return cls(code=code, filepath=filepath)
        
        # 处理缺少结束```的情况 - 修复agents.py提取动作字符串时截断的问题
        incomplete_patterns = [
            # 双引号版本
            r'EditFile\(filepath="([^"]+)"\)\s*:\s*\n```[^\n]*\n(.*)',
            # 单引号版本
            r'EditFile\(filepath=\'([^\']+)\'\)\s*:\s*\n```[^\n]*\n(.*)',
            # 缺少右括号的版本 - 语法错误但需要容错
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n```[^\n]*\n(.*)',
            r'EditFile\(filepath=\'([^\']+)\'\s*:\s*\n```[^\n]*\n(.*)',
        ]
        
        for pattern in incomplete_patterns:
            incomplete_match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if incomplete_match:
                filepath = incomplete_match.group(1).strip()
                code = incomplete_match.group(2).strip()
                if filepath and code:
                    return cls(code=code, filepath=filepath)
        
        # 处理单引号和三引号格式 - 如 EditFile(filepath='...':'''...''')
        triple_quote_patterns = [
            # 完整的三引号格式 - 双引号版本
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*?)\n\'\'\'\s*\)',
            r'EditFile\(filepath="([^"]+)"\s*:\s*\'\'\'\s*\n(.*?)\n\'\'\'\s*\)',
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*(.*?)\s*\'\'\'\s*\)',
            # 完整的三引号格式 - 单引号版本
            r"EditFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*?)\n'''\s*\)",
            r"EditFile\(filepath='([^']+)'\s*:\s*'''\s*\n(.*?)\n'''\s*\)",
            r"EditFile\(filepath='([^']+)'\s*:\s*\n'''\s*(.*?)\s*'''\s*\)",
            # 缺少结束三引号的格式 - 双引号版本
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*)',
            r'EditFile\(filepath="([^"]+)"\s*:\s*\'\'\'\s*\n(.*)',
            # 缺少结束三引号的格式 - 单引号版本
            r"EditFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*)",
            r"EditFile\(filepath='([^']+)'\s*:\s*'''\s*\n(.*)",
            # 缺少右括号 + 三引号格式 - 双引号版本
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*?)\n\'\'\'\s*\)',
            r'EditFile\(filepath="([^"]+)"\s*:\s*\'\'\'\s*\n(.*?)\n\'\'\'\s*\)',
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*(.*?)\s*\'\'\'\s*\)',
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*)',
            r'EditFile\(filepath="([^"]+)"\s*:\s*\'\'\'\s*\n(.*)',
            # 缺少右括号 + 三引号格式 - 单引号版本
            r"EditFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*?)\n'''\s*\)",
            r"EditFile\(filepath='([^']+)'\s*:\s*'''\s*\n(.*?)\n'''\s*\)",
            r"EditFile\(filepath='([^']+)'\s*:\s*\n'''\s*(.*?)\s*'''\s*\)",
            r"EditFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*)",
            r"EditFile\(filepath='([^']+)'\s*:\s*'''\s*\n(.*)",
        ]
        
        for pattern in triple_quote_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                code = match.group(2).strip() if len(match.groups()) >= 2 else ""
                # 清理代码中可能包含的尾部'''标记
                code = re.sub(r'\n\'\'\'\s*$', '', code)
                if filepath:  # 允许空代码
                    return cls(code=code, filepath=filepath)
        
        # 处理更宽松的参数格式，包括额外的空格
        flexible_patterns = [
            # 参数周围有额外空格的情况
            r'EditFile\(\s*filepath\s*=\s*"([^"]+)"\s*\)\s*:\s*\n```[^\n]*\n(.*?)```',
            r"EditFile\(\s*filepath\s*=\s*'([^']+)'\s*\)\s*:\s*\n```[^\n]*\n(.*?)```",
            r'EditFile\(\s*filepath\s*=\s*"([^"]+)"\s*\)\s*:\s*\n```[^\n]*\n(.*)',
            r"EditFile\(\s*filepath\s*=\s*'([^']+)'\s*\)\s*:\s*\n```[^\n]*\n(.*)",
            # 混合引号的情况（虽然语法错误，但容错处理）
            r'EditFile\(filepath="([^"\']+)["\']?\s*:\s*\n```[^\n]*\n(.*)',
            r"EditFile\(filepath='([^\"']+)[\"']?\s*:\s*\n```[^\n]*\n(.*)",
            # 空内容的特殊处理
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n```\s*\n\s*```',
            r"EditFile\(filepath='([^']+)'\s*:\s*\n```\s*\n\s*```",
            # 处理标准三引号但缺少右括号的情况
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n(.*?)\n\'\'\'\s*',
            r"EditFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n(.*?)\n'''\s*",
        ]
        
        for pattern in flexible_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                # 清理 filepath 中的混合引号问题
                filepath = re.sub(r'["\']$', '', filepath)  # 移除尾部的引号
                if len(match.groups()) >= 2 and match.group(2):
                    code = match.group(2).strip()
                    # 清理代码中可能的标记
                    code = re.sub(r'^```\s*$', '', code)  # 移除只有```的行
                    code = re.sub(r'^\s*```\s*\n?', '', code)  # 移除开头的```
                    code = re.sub(r'\n\s*```\s*$', '', code)  # 移除结尾的```
                else:
                    code = ""  # 处理空内容的情况
                if filepath:  # 即使代码为空也允许
                    return cls(code=code, filepath=filepath)
        
        # 处理空代码块的特殊情况
        empty_block_patterns = [
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n```\s*\n\s*```\s*',
            r"EditFile\(filepath='([^']+)'\s*:\s*\n```\s*\n\s*```\s*",
            r'EditFile\(filepath="([^"]+)"\s*:\s*\n\'\'\'\s*\n\s*\'\'\'\s*',
            r"EditFile\(filepath='([^']+)'\s*:\s*\n'''\s*\n\s*'''\s*",
        ]
        
        for pattern in empty_block_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                if filepath:
                    return cls(code="", filepath=filepath)
        
        # 处理混合引号的特殊情况 
        mixed_quote_patterns = [
            # 双引号开头，单引号结尾的错误格式
            r'EditFile\(filepath="([^"\']*)\'\s*:\s*\n```[^\n]*\n(.*?)```',
            r'EditFile\(filepath="([^"\']*)\'\s*:\s*\n```[^\n]*\n(.*)',
            # 单引号开头，双引号结尾的错误格式
            r"EditFile\(filepath='([^\"']*)\"\s*:\s*\n```[^\n]*\n(.*?)```",
            r"EditFile\(filepath='([^\"']*)\"\s*:\s*\n```[^\n]*\n(.*)",
        ]
        
        for pattern in mixed_quote_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                code = match.group(2).strip() if len(match.groups()) >= 2 else ""
                if filepath:
                    return cls(code=code, filepath=filepath)
        
        # 最后的容错模式 - 尝试匹配任何包含EditFile的内容
        final_fallback_patterns = [
            # 匹配任何形式的EditFile，无论语法多么错误
            r'EditFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^)]*\).*?```[^\n]*\n(.*?)```',
            r'EditFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^)]*\).*?```[^\n]*\n(.*)',
            r'EditFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^)]*\).*?\'\'\'\s*\n(.*?)\'\'\'\s*',
            r'EditFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^)]*\).*?\'\'\'\s*\n(.*)',
            # 处理所有可能的语法错误和缺失
            r'EditFile\([^)]*filepath[^)]*["\']([^"\']+)["\'][^):]*[:)]?\s*[^`\']*[`\']{3}[^\n]*\n(.*)',
        ]
        
        for pattern in final_fallback_patterns:
            match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
            if match:
                filepath = match.group(1).strip()
                code = match.group(2).strip() if len(match.groups()) >= 2 else ""
                # 清理代码中的尾部标记
                code = re.sub(r'\n[`\']{3,}\s*$', '', code)
                # 清理开头的多余标记
                code = re.sub(r'^[`\']{3,}[^\n]*\n', '', code) 
                if filepath:
                    return cls(code=code, filepath=filepath)
        
        return None    



@dataclass
class LOCAL_DB_SQL(Action):

    action_type: str = field(default="sql_command",init=False,repr=False,metadata={"help": 'type of action, c.f., "sql_command"'})
    code: str = field(metadata={"help": 'SQL command to execute'})
    file_path: str = field(default=None,metadata={"help": 'path to the database file'})
    output: str = field(default=None, metadata={"help": 'output file path or "direct"'})

    @classmethod
    def get_action_description(cls) -> str:
        return """
## SQL Action
* Signature: LOCAL_DB_SQL(file_path="database.sqlite", command="sql_command", output="path/to/output_file.csv" or "direct")
* Description: Executes an SQL command on the specified database file(SQLITE or Duckdb). If `output` is set to a file path, the results are saved to this CSV file; if set to 'direct', results are displayed directly.
* Examples:
  - Example1: LOCAL_DB_SQL(file_path="data.sqlite", command="SELECT name FROM sqlite_master WHERE type='table'", output="directly")
  - Example2: LOCAL_DB_SQL(file_path="data.sqlite", command="SELECT * FROM users", output="users_output.csv")
"""
    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        # Multiple patterns to handle different formats and quote styles
        positional = cls._parse_args_positionally(text)
        if positional:
            file_path, command, output = positional
            return cls(file_path=file_path, code=command, output=output)

        patterns = [
            # Standard format with different quote combinations
            r'LOCAL_DB_SQL\(file_path="([^"]*)",\s*command="([^"]*)",\s*output="([^"]*)"\)',
            r"LOCAL_DB_SQL\(file_path='([^']*)',\s*command='([^']*)',\s*output='([^']*)'\)",
            r'LOCAL_DB_SQL\(file_path="""([^"]*?)""",\s*command="""([^"]*?)""",\s*output="""([^"]*?)"""\)',
            r"LOCAL_DB_SQL\(file_path='''([^']*?)''',\s*command='''([^']*?)''',\s*output='''([^']*?)'''\)",
            
            # Mixed quote styles
            r'LOCAL_DB_SQL\(file_path="([^"]*)",\s*command=\'([^\']*)\',\s*output="([^"]*)"\)',
            r"LOCAL_DB_SQL\(file_path='([^']*)',\s*command=\"([^\"]*)\",\s*output='([^']*)'\)",
            
            # With optional spaces around equals signs
            r'LOCAL_DB_SQL\(\s*file_path\s*=\s*"([^"]*)",\s*command\s*=\s*"([^"]*)",\s*output\s*=\s*"([^"]*)"\)',
            r"LOCAL_DB_SQL\(\s*file_path\s*=\s*'([^']*)',\s*command\s*=\s*'([^']*)',\s*output\s*=\s*'([^']*)'\)",
            
            # Alternative parameter names (sql_query instead of command)
            r'LOCAL_DB_SQL\(file_path="([^"]*)",\s*sql_query="([^"]*)",\s*output="([^"]*)"\)',
            r"LOCAL_DB_SQL\(file_path='([^']*)',\s*sql_query='([^']*)',\s*output='([^']*)'\)",
            
            # Different parameter orders
            r'LOCAL_DB_SQL\(command=["\']([^"\']*)["\'],\s*file_path=["\']([^"\']*)["\'],\s*output=["\']([^"\']*)["\'\)]',
            r'LOCAL_DB_SQL\(output=["\']([^"\']*)["\'],\s*file_path=["\']([^"\']*)["\'],\s*command=["\']([^"\']*)["\'\)]',
            
            # Without quotes (risky but sometimes happens)
            r'LOCAL_DB_SQL\(file_path=([^,)]+),\s*command=([^,)]+),\s*output=([^,)]*)\)',
            
            # Fallback patterns for malformed syntax
            r'LOCAL_DB_SQL\([^)]*file_path[^)]*?["\']([^"\']+)["\'][^)]*?command[^)]*?["\']([^"\']*)["\'][^)]*?output[^)]*?["\']([^"\']*)["\'][^)]*\)',
            r'LOCAL_DB_SQL\([^)]*file_path[^)]*?["\']([^"\']+)["\'][^)]*?sql_query[^)]*?["\']([^"\']*)["\'][^)]*?output[^)]*?["\']([^"\']*)["\'][^)]*\)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, flags=re.DOTALL)
            if matches:
                match = matches[-1]
                if len(match) == 3:
                    # Handle different parameter orders based on pattern
                    if r'command=["\']([^"\']*)["\'],\s*file_path=' in pattern:
                        # command comes first: command, file_path, output
                        command, file_path, output = match
                    elif r'output=["\']([^"\']*)["\'],\s*file_path=' in pattern:
                        # output comes first: output, file_path, command  
                        output, file_path, command = match
                    elif 'sql_query=' in pattern:
                        # sql_query instead of command: file_path, command (sql_query), output
                        file_path, command, output = match
                    else:
                        # standard order: file_path, command, output
                        file_path, command, output = match
                    
                    # Clean up the extracted values
                    file_path = remove_quote(file_path.strip())
                    command = remove_quote(command.strip())
                    output = remove_quote(output.strip())
                    
                    if file_path and command and output:
                        return cls(file_path=file_path, code=command, output=output)
        
        # Try more flexible parsing for incomplete or malformed inputs
        flexible_patterns = [
            # Missing quotes but recognizable structure
            r'LOCAL_DB_SQL\([^)]*file_path[^)]*?=([^,)]+)[^)]*?command[^)]*?=([^,)]+)[^)]*?output[^)]*?=([^,)]*)\)',
            # With SQL keywords that might help identify the command
            r'LOCAL_DB_SQL\([^)]*file_path[^)]*?["\']([^"\']+)["\'][^)]*?(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|SHOW|DESCRIBE)[^)]*?["\']([^"\']*)["\'][^)]*\)',
        ]
        
        for pattern in flexible_patterns:
            matches = re.findall(pattern, text, flags=re.DOTALL | re.IGNORECASE)
            if matches:
                match = matches[-1]
                if len(match) >= 2:
                    if len(match) == 2:
                        # SQL keyword pattern
                        file_path, command_part = match[0], match[1]
                        # Try to find the full command and output
                        full_match = re.search(
                            rf'LOCAL_DB_SQL\([^)]*file_path[^)]*?["\']({re.escape(file_path)})["\'][^)]*?["\']([^"\']*{re.escape(command_part)}[^"\']*)["\'][^)]*?["\']([^"\']*)["\'][^)]*\)',
                            text, flags=re.DOTALL | re.IGNORECASE
                        )
                        if full_match:
                            file_path, command, output = full_match.groups()
                        else:
                            # Fallback: assume minimal output
                            command = command_part
                            output = "direct"
                    else:
                        file_path, command, output = match[0], match[1], match[2] if len(match) > 2 else "direct"
                    
                    # Clean up the extracted values
                    file_path = remove_quote(file_path.strip())
                    command = remove_quote(command.strip()) 
                    output = remove_quote(output.strip()) if output else "direct"
                    
                    if file_path and command:
                        return cls(file_path=file_path, code=command, output=output)
        
        # As a last resort, try to extract arguments positionally to handle nested quotes
        positional = cls._parse_args_positionally(text)
        if positional:
            file_path, command, output = positional
            return cls(file_path=file_path, code=command, output=output)
        return None

    @staticmethod
    def _parse_args_positionally(text: str) -> Optional[tuple[str, str, str]]:
        """Extract file_path, command, output by scanning text when regex fails."""
        def _extract_value(src: str, key: str, next_key: Optional[str]) -> Optional[str]:
            idx = src.find(key)
            if idx == -1:
                return None
            idx = src.find("=", idx)
            if idx == -1:
                return None
            idx += 1
            while idx < len(src) and src[idx].isspace():
                idx += 1
            if idx >= len(src):
                return None

            start = idx
            pos = idx
            in_quote: Optional[str] = None
            escape = False
            paren_depth = 0
            end = len(src)

            while pos < len(src):
                ch = src[pos]
                if escape:
                    escape = False
                elif ch == "\\" and in_quote:
                    escape = True
                elif in_quote:
                    if ch == in_quote:
                        in_quote = None
                else:
                    if ch in ('"', "'"):
                        in_quote = ch
                    elif ch == "(":
                        paren_depth += 1
                    elif ch == ")":
                        if paren_depth == 0 and next_key is None:
                            end = pos
                            break
                        paren_depth = max(paren_depth - 1, 0)
                    elif ch == "," and paren_depth == 0:
                        lookahead = pos + 1
                        while lookahead < len(src) and src[lookahead].isspace():
                            lookahead += 1
                        if next_key and src.startswith(next_key, lookahead):
                            end = pos
                            break
                pos += 1

            value = src[start:end].strip().rstrip(",")
            return value or None

        raw_file = _extract_value(text, "file_path", "command")
        raw_command = _extract_value(text, "command", "output")
        raw_output = _extract_value(text, "output", None)

        if not all([raw_file, raw_command, raw_output]):
            return None

        file_path = remove_quote(raw_file.strip())
        command = remove_quote(raw_command.strip())
        output = remove_quote(raw_output.strip())

        if not (file_path and command and output):
            return None
        return file_path, command, output

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(file_path="{self.file_path}", command="{self.code}", output="{self.output}")'
    

@dataclass
class BIGQUERY_EXEC_SQL(Action):
    action_type: str = field(default="execute_bigquery_SQL",init=False,repr=False,metadata={"help": 'type of action, c.f., "exec_bq_sql"'})
    sql_query: str = field(metadata={"help": 'SQL query to execute'})
    is_save: bool = field(metadata={"help": 'whether to save result to CSV'})
    save_path: str = field(default=None, metadata={"help": 'path where the output CSV file is saved if is_save is True'})

    @classmethod
    def get_action_description(cls) -> str:
        return """
## BIGQUERY_EXEC_SQL Action
* Signature: BIGQUERY_EXEC_SQL(sql_query="SELECT * FROM your_table", is_save=True, save_path="./output_file.csv")
* Description: Executes a SQL query on Google Cloud BigQuery. If `is_save` is True, the results are saved to a specified CSV file; otherwise, results are printed.
If you estimate that the number of returned rows is small, you can set is_save=False, to directly view the results. If you estimate that the number of returned rows is large, be sure to set is_save = True.
The `save_path` CSV must be under the `./` directory.
* Examples:
  - Example1: BIGQUERY_EXEC_SQL(sql_query="SELECT count(*) FROM sales", is_save=False)
  - Example2: BIGQUERY_EXEC_SQL(sql_query="SELECT user_id, sum(purchases) FROM transactions GROUP BY user_id", is_save=True, save_path="./result.csv")
"""

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional['BIGQUERY_EXEC_SQL']:
        pattern = r'BIGQUERY_EXEC_SQL\(sql_query=(?P<quote>\"\"\"|\"|\'|\"\"|\'\')(.*?)(?P=quote), is_save=(True|False)(, save_path=(?P<quote2>\"|\'|\"\"|\'\')(.*?)(?P=quote2))?\)'
        
        match = re.search(pattern, text, flags=re.DOTALL)
        if match:
            sql_query = match.group(2).strip()  # Capturing the SQL query part
            is_save = match.group(3).strip().lower() == 'true'  # Determining is_save
            save_path = match.group(6) if match.group(6) else ""  # Optional save_path handling
            
            return cls(sql_query=sql_query, is_save=is_save, save_path=save_path)
        return None



    def __repr__(self) -> str:
        save_info = f', save_path="{self.save_path}"' if self.is_save else ""
        return f'BIGQUERY_EXEC_SQL(sql_query="{self.sql_query}", is_save={self.is_save}{save_info})'

    

@dataclass
class SNOWFLAKE_EXEC_SQL(Action):
    action_type: str = field(default="execute_snowflake_SQL", init=False, repr=False, metadata={"help": 'type of action, c.f., "exec_sf_sql"'})
    sql_query: str = field(metadata={"help": 'SQL query to execute'})
    is_save: bool = field(metadata={"help": 'whether to save result to CSV'})
    save_path: str = field(default=None, metadata={"help": 'path where the output CSV file is saved if is_save is True'})

    @classmethod
    def get_action_description(cls) -> str:
        return """
## SNOWFLAKE_EXEC_SQL Action
* Signature: SNOWFLAKE_EXEC_SQL(sql_query="SELECT * FROM your_table", is_save=True, save_path="./output_file.csv")
* Description: Executes a SQL query on Snowflake. If `is_save` is True, the results are saved to a specified CSV file; otherwise, results are printed.
If you estimate that the number of returned rows is small, you can set is_save=False, to directly view the results. If you estimate that the number of returned rows is large, be sure to set is_save = True.
The `save_path` CSV must be under the `./` directory.
* Examples:
  - Example1: SNOWFLAKE_EXEC_SQL(sql_query="SELECT count(*) FROM sales", is_save=False)
  - Example2: SNOWFLAKE_EXEC_SQL(sql_query="SELECT user_id, sum(purchases) FROM transactions GROUP BY user_id", is_save=True, save_path="./result.csv")
"""

    # @classmethod
    # def parse_action_from_text(cls, text: str) -> Optional['SNOWFLAKE_EXEC_SQL']:
    #     pattern = r'SNOWFLAKE_EXEC_SQL\(sql_query=(?P<quote>\"\"\"|\"|\'|\"\"|\'\')(.*?)(?P=quote), is_save=(True|False)(, save_path=(?P<quote2>\"|\'|\"\"|\'\')(.*?)(?P=quote2))?\)'
        
    #     match = re.search(pattern, text, flags=re.DOTALL)
    #     if match:
    #         sql_query = match.group(2).strip()  # Capturing the SQL query part
    #         is_save = match.group(3).strip().lower() == 'true'  # Determining is_save
    #         save_path = match.group(6) if match.group(6) else ""  # Optional save_path handling
            
    #         return cls(sql_query=sql_query, is_save=is_save, save_path=save_path)
    #     return None

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional['SNOWFLAKE_EXEC_SQL']:
        pattern = r'''
            SNOWFLAKE_EXEC_SQL\(
                \s*sql_query\s*=\s*
                (?P<quote_sql>\"\"\"|\"|\'\'\'|\'|\"\"\")  # Match opening quote for sql_query
                (?P<sql_query>.*?)
                (?<!\\)(?P=quote_sql)                      # Match closing quote for sql_query
                ,\s*is_save\s*=\s*
                (?P<is_save>True|False)
                (?:,\s*save_path\s*=\s*
                    (?P<quote_path>\"\"\"|\"|\'\'\'|\'|\"\"\")  # Match opening quote for save_path
                    (?P<save_path>.*?)
                    (?<!\\)(?P=quote_path)                     # Match closing quote for save_path
                )?
                \s*\)
        '''
        # Use re.VERBOSE to allow multiline and commented pattern
        match = re.search(pattern, text, flags=re.DOTALL | re.VERBOSE)
        if match:
            # Extracting sql_query
            sql_query_raw = match.group('sql_query')
            sql_query = sql_query_raw.replace(r'\"', '"').replace(r"\'", "'").replace('\\\\', '\\')

            # Extracting is_save
            is_save_str = match.group('is_save')
            is_save = is_save_str.strip().lower() == 'true'

            # Extracting save_path if present
            save_path = ""
            if match.group('save_path'):
                save_path_raw = match.group('save_path')
                save_path = save_path_raw.replace(r'\"', '"').replace(r"\'", "'").replace('\\\\', '\\')

            return cls(sql_query=sql_query, is_save=is_save, save_path=save_path)
        return None


    def __repr__(self) -> str:
        save_info = f', save_path="{self.save_path}"' if self.is_save else ""
        return f'SNOWFLAKE_EXEC_SQL(sql_query="{self.sql_query}", is_save={self.is_save}{save_info})'



    
@dataclass
class SF_GET_TABLES(Action):

    action_type: str = field(default="get_tables",init=False,repr=False,metadata={"help": 'type of action, c.f., "get_tables"'})

    database_name: str = field(metadata={"help": 'snowflake database name'})

    schema_name: str = field(metadata={"help": 'Dataset / schema name within the database'})

    save_path: str = field(metadata={"help": 'path where the output CSV file is saved'})

    @classmethod
    def get_action_description(cls) -> str:
        return """
## SF_GET_TABLES Action
* Signature: SF_GET_TABLES(database_name="your_database_name", schema_name="your_schema_name", save_path="path/to/output_file.csv")
* Description: Executes a query to fetch all table names and their corresponding DDL from the specified dataset in Snowflake. The results are saved to the specified CSV file.
* Examples:
  - Example1: SF_GET_TABLES(database_name="FINANCE__ECONOMICS", schema_name="CYBERSYN", save_path="dataset_metadata.csv")
"""
    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'SF_GET_TABLES\(database_name=(.*?), schema_name=(.*?), save_path=(.*?)\)', text, flags=re.DOTALL)
        if matches:
            database_name, schema_name, save_path = (item.strip() for item in matches[-1])
            return cls(database_name=remove_quote(database_name), schema_name=remove_quote(schema_name), save_path=remove_quote(save_path))
        return None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(database_name="{self.database_name}", schema_name="{self.schema_name}", save_path="{self.save_path}")'
    


@dataclass
class SF_GET_TABLE_INFO(Action):

    action_type: str = field(default="get_table_info",init=False,repr=False,metadata={"help": 'type of action, c.f., "get_table_info"'})

    database_name: str = field(metadata={"help": 'Google Cloud project name'})

    schema_name: str = field(metadata={"help": 'Dataset name within the project'})

    table: str = field(metadata={"help": 'Name of the table to fetch information from'})

    save_path: str = field(metadata={"help": 'path where the output CSV file is saved'})

    @classmethod
    def get_action_description(cls) -> str:
        return """
## SF_GET_TABLE_INFO Action
* Signature: SF_GET_TABLE_INFO(database_name="your_database_name", schema_name="your_schema_name", table="table_name", save_path="path/to/output_file.csv")
* Description: Executes a query to fetch all column information (field path, data type, and description) from the specified table in the dataset in Snowflake. The results are saved to the specified CSV file.
* Examples:
  - Example1: SF_GET_TABLE_INFO(database_name="FINANCE__ECONOMICS", schema_name="CYBERSYN", table="BANK_FOR_INTERNATIONAL_SETTLEMENTS_TIMESERIES", save_path="bank_for_international_settlements_timeseries_info.csv")
"""
    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'SF_GET_TABLE_INFO\(database_name=(.*?), schema_name=(.*?), table=(.*?), save_path=(.*?)\)', text, flags=re.DOTALL)
        if matches:
            database_name, schema_name, table, save_path = (item.strip() for item in matches[-1])
            return cls(database_name=remove_quote(database_name), schema_name=remove_quote(schema_name), table=remove_quote(table), save_path=remove_quote(save_path))
        return None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(database_name="{self.database_name}", schema_name="{self.schema_name}", table="{self.table}", save_path="{self.save_path}")'




    
@dataclass
class BQ_GET_TABLES(Action):

    action_type: str = field(default="get_tables",init=False,repr=False,metadata={"help": 'type of action, c.f., "get_tables"'})

    database_name: str = field(metadata={"help": 'Google Cloud project name'})

    dataset_name: str = field(metadata={"help": 'Dataset name within the project'})

    save_path: str = field(metadata={"help": 'path where the output CSV file is saved'})

    @classmethod
    def get_action_description(cls) -> str:
        return """
## GET_TABLES Action
* Signature: GET_TABLES(database_name="your_database_name", dataset_name="your_dataset_name", save_path="path/to/output_file.csv")
* Description: Executes a query to fetch all table names and their corresponding DDL from the specified dataset in Google Cloud BigQuery. The results are saved to the specified CSV file.
  - The BigQuery id of a table is usually in the form of database_name.dataset_name.table_name. This action mainly focuses on the tables under dataset_name.
* Examples:
  - Example1: GET_TABLES(database_name="bigquery-public-data", dataset_name="new_york", save_path="dataset_metadata.csv")
"""
    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'GET_TABLES\(database_name=(.*?), dataset_name=(.*?), save_path=(.*?)\)', text, flags=re.DOTALL)
        if matches:
            database_name, dataset_name, save_path = (item.strip() for item in matches[-1])
            return cls(database_name=remove_quote(database_name), dataset_name=remove_quote(dataset_name), save_path=remove_quote(save_path))
        return None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(database_name="{self.database_name}", dataset_name="{self.dataset_name}", save_path="{self.save_path}")'
    
    
@dataclass
class BQ_GET_TABLE_INFO(Action):

    action_type: str = field(default="get_table_info",init=False,repr=False,metadata={"help": 'type of action, c.f., "get_table_info"'})

    database_name: str = field(metadata={"help": 'Google Cloud project name'})

    dataset_name: str = field(metadata={"help": 'Dataset name within the project'})

    table: str = field(metadata={"help": 'Name of the table to fetch information from'})

    save_path: str = field(metadata={"help": 'path where the output CSV file is saved'})

    @classmethod
    def get_action_description(cls) -> str:
        return """
## GET_TABLE_INFO Action
* Signature: GET_TABLE_INFO(database_name="your_database_name", dataset_name="your_dataset_name", table="table_name", save_path="path/to/output_file.csv")
* Description: Executes a query to fetch all column information (field path, data type, and description) from the specified table in the dataset in Google Cloud BigQuery. The results are saved to the specified CSV file.
 - The BigQuery id of a table is usually in the form of database_name.dataset_name.table_name.
* Examples:
  - Example1: GET_TABLE_INFO(database_name="bigquery-public-data", dataset_name="samples", table="shakespeare", save_path="shakespeare_info.csv")
"""
    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'GET_TABLE_INFO\(database_name=(.*?), dataset_name=(.*?), table=(.*?), save_path=(.*?)\)', text, flags=re.DOTALL)
        if matches:
            database_name, dataset_name, table, save_path = (item.strip() for item in matches[-1])
            return cls(database_name=remove_quote(database_name), dataset_name=remove_quote(dataset_name), table=remove_quote(table), save_path=remove_quote(save_path))
        return None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(database_name="{self.database_name}", dataset_name="{self.dataset_name}", table="{self.table}", save_path="{self.save_path}")'


@dataclass
class BQ_SAMPLE_ROWS(Action):

    action_type: str = field(default="bq_sample_rows",init=False,repr=False,metadata={"help": 'type of action, c.f., "bq_sample_rows"'})

    database_name: str = field(metadata={"help": 'Google Cloud project name'})

    dataset_name: str = field(metadata={"help": 'Dataset name within the project'})

    table: str = field(metadata={"help": 'Name of the table to sample data from'})

    row_number: int = field(metadata={"help": 'Number of rows to sample'})

    save_path: str = field(metadata={"help": 'path where the output JSON file is saved'})

    @classmethod
    def get_action_description(cls) -> str:
        return """
## BQ_SAMPLE_ROWS Action
* Signature: BQ_SAMPLE_ROWS(database_name="your_database_name", dataset_name="your_dataset_name", table="table_name", row_number=3, save_path="path/to/output_file.json")
* Description: Executes a query to sample a specified number of rows from the table in the dataset in Google Cloud BigQuery using the TABLESAMPLE SYSTEM method. The results are saved in JSON format to the specified path.
* Examples:
  - Example1: BQ_SAMPLE_ROWS(database_name="bigquery-public-data", dataset_name="samples", table="shakespeare", row_number=3, save_path="shakespeare_sample_data.json")
"""
    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'BQ_SAMPLE_ROWS\(database_name=(.*?), dataset_name=(.*?), table=(.*?), row_number=(.*?), save_path=(.*?)\)', text, flags=re.DOTALL)
        if matches:
            database_name, dataset_name, table, row_number, save_path = (item.strip() for item in matches[-1])
            return cls(database_name=remove_quote(database_name), dataset_name=remove_quote(dataset_name), table=remove_quote(table), row_number=int(row_number), save_path=remove_quote(save_path))
        return None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(database_name="{self.database_name}", dataset_name="{self.dataset_name}", table="{self.table}", row_number={self.row_number}, save_path="{self.save_path}")'
    



@dataclass
class SF_SAMPLE_ROWS(Action):

    action_type: str = field(default="sf_sample_rows",init=False,repr=False,metadata={"help": 'type of action, c.f., "sf_sample_rows"'})

    database_name: str = field(metadata={"help": 'Snowflake database name'})

    schema_name: str = field(metadata={"help": 'Schema name within the database'})

    table: str = field(metadata={"help": 'Name of the table to sample data from'})

    row_number: int = field(metadata={"help": 'Number of rows to sample'})

    save_path: str = field(metadata={"help": 'path where the output JSON file is saved'})

    @classmethod
    def get_action_description(cls) -> str:
        return """
## SF_SAMPLE_ROWS Action
* Signature: SF_SAMPLE_ROWS(database_name="your_database_name", schema_name="your_schema_name", table="table_name", row_number=3, save_path="path/to/output_file.json")
* Description: Executes a query to sample a specified number of rows from the table in the schema in Snowflake. The results are saved in JSON format to the specified path.
* Examples:
  - Example1: SF_SAMPLE_ROWS(database_name="FINANCE__ECONOMICS", schema_name="CYBERSYN", table="BANK_FOR_INTERNATIONAL_SETTLEMENTS_TIMESERIES", row_number=3, save_path="bank_sample_data.json")
"""
    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'SF_SAMPLE_ROWS\(database_name=(.*?), schema_name=(.*?), table=(.*?), row_number=(.*?), save_path=(.*?)\)', text, flags=re.DOTALL)
        if matches:
            database_name, schema_name, table, row_number, save_path = (item.strip() for item in matches[-1])
            return cls(database_name=remove_quote(database_name), schema_name=remove_quote(schema_name), table=remove_quote(table), row_number=int(row_number), save_path=remove_quote(save_path))
        return None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(database_name="{self.database_name}", schema_name="{self.schema_name}", table="{self.table}", row_number={self.row_number}, save_path="{self.save_path}")'
    



@dataclass
class Terminate(Action):

    action_type: str = field(
        default="terminate",
        init=False,
        repr=False,
        metadata={"help": "terminate action representing the task is finished, or you think it is impossible for you to complete the task"}
    )

    output: Optional[str] = field(
        default=None,
        metadata={"help": "answer to the task or output file path or 'FAIL', if exists"}
    )

    code : str = field(
        default=''
    )

    @classmethod
    def get_action_description(cls, language: str = "zh") -> str:
        language = (language or "zh").lower()
        if language == "en":
            return """
## Terminate Action
* Signature: Terminate(output="stage1 report saved" or other short confirmation)
* Description: Call this when the stage is complete and the required markdown/report has been written. Use a concise English confirmation, and do not paste the full report into the output string.
* Examples:
  - Example1: Terminate(output="stage1 report saved")
  - Example2: Terminate(output="visual enhancements completed")
"""
        return """
## Terminate Action
* Signature: Terminate(output="报告/insight/结论内容的具体内容")
* Description:When you think you have completed the task, you can terminate.
* Examples:
  - Example1: Terminate(output="报告/insight/结论内容的具体内容")
"""

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(output="{self.output}")'

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        # Use a more robust pattern that handles nested parentheses properly
        patterns = [
            # Pattern 1: Handle quoted strings with proper quote matching
            r'Terminate\(output=(["\'])((?:\\.|(?!\1).)*)\1\)',
            # Pattern 2: Handle triple quoted strings
            r'Terminate\(output=(""")(.*?)\1\)',
            r"Terminate\(output=(''')(.*?)\1\)",
            # Pattern 3: Match balanced parentheses for unquoted content
            r'Terminate\(output=([^")]*(?:\([^)]*\)[^")]*)*)\)',
            # Pattern 4: Fallback - match to the last closing parenthesis
            r'Terminate\(output=(.*)\)(?![^(]*\))',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, flags=re.DOTALL)
            if matches:
                if isinstance(matches[-1], tuple):
                    # For patterns that capture quotes, take the content part
                    output = matches[-1][1] if len(matches[-1]) > 1 else matches[-1][0]
                else:
                    output = matches[-1]
                return cls(output=remove_quote(output.strip()))

        return None
    
