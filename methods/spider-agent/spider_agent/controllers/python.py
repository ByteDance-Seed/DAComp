import ast
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from spider_agent.agent.sql_template import (
    LOCAL_SQL_TEMPLATE,
    BQ_GET_TABLES_TEMPLATE,
    BQ_GET_TABLE_INFO_TEMPLATE,
    BQ_SAMPLE_ROWS_TEMPLATE,
    BQ_EXEC_SQL_QUERY_TEMPLATE,
)
from spider_agent.agent.sql_template import (
    SF_EXEC_SQL_QUERY_TEMPLATE,
    SF_GET_TABLE_INFO_TEMPLATE,
    SF_GET_TABLES_TEMPLATE,
    SF_SAMPLE_ROWS_TEMPLATE,
)

logger = logging.getLogger("spider_agent.pycontroller")


class PythonController:
    _SIMHEI_PATH = (Path(__file__).resolve().parent.parent / "envs" / "SimHei.ttf").as_posix()
    _SITE_CUSTOMIZE = Path(__file__).resolve().parent.parent / "envs" / "sitecustomize.py"
    _MATPLOTLIB_IMPORT_PATTERNS = (
        "import matplotlib as plt",
        "import matplotlib.pyplot as plt",
        "from matplotlib import pyplot as plt",
    )
    _MATPLOTLIB_RC_LINES = [
        "from pathlib import Path",
        "from matplotlib import font_manager",
        f"font_path = Path('{_SIMHEI_PATH}')",
        "if font_path.exists():",
        "    font_manager.fontManager.addfont(str(font_path))",
        "    font = font_manager.FontProperties(fname=font_path)",
        "    plt.rcParams['font.sans-serif'] = [font.get_name(), 'SimHei']",
        "    plt.rcParams['font.family'] = 'sans-serif'",
        "    plt.rcParams['axes.unicode_minus'] = False",
        "    plt.rcParams['pdf.fonttype'] = 42",
        "    plt.rcParams['ps.fonttype'] = 42",
        "    plt.rcParams['svg.fonttype'] = 'path'",
        "    plt.rcParams['mathtext.fontset'] = 'stix'",
        "    plt.rcParams['mathtext.rm'] = 'STIXGeneral'",
    ]

    def __init__(self, root_dir: str, virtual_work_dir: str = "/workspace", language: str = "zh"):
        self.root_dir = Path(root_dir).resolve()
        self.virtual_work_dir = virtual_work_dir
        self.work_dir = virtual_work_dir
        self._real_work_dir = self.root_dir
        self._last_sql_signature = None
        self._consecutive_sql_errors = 0
        self._sql_repeat_limit = 2
        self.language = (language or "zh").lower()
        self._extra_pythonpath: Optional[str] = None
        self._setup_sitecustomize()

    def _virtual_to_real(self, path: str) -> Path:
        if not path:
            return self.root_dir
        if self.virtual_work_dir and path.startswith(self.virtual_work_dir):
            remainder = path[len(self.virtual_work_dir):].lstrip("/")
            return (self.root_dir / remainder).resolve()
        return Path(path).expanduser().resolve()

    def _replace_virtual_paths(self, command: str) -> str:
        if not self.virtual_work_dir:
            return command
        return command.replace(self.virtual_work_dir, str(self.root_dir))

    def _run_subprocess(self, command: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.setdefault("LANG", "en_US.UTF-8")
        env.setdefault("LC_ALL", "en_US.UTF-8")
        env.setdefault("LC_CTYPE", "en_US.UTF-8")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if self._extra_pythonpath:
            env["PYTHONPATH"] = (
                f"{self._extra_pythonpath}:{env['PYTHONPATH']}"
                if "PYTHONPATH" in env and env["PYTHONPATH"]
                else self._extra_pythonpath
            )
        return subprocess.run(
            ["bash", "-lc", command],
            cwd=str(self._real_work_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

    def get_file(self, file_path: str):
        """
        Gets a file from the workspace.
        """
        real_file_path = self.get_real_file_path(file_path)
        try:
            with open(real_file_path, "r", encoding="utf-8") as file:
                return file.read()
        except FileNotFoundError:
            logger.warning("File not found: %s", file_path)
        except Exception as exc:
            logger.error("Failed to read file %s: %s", file_path, exc)
        return ""

    def _wrap_with_print(self, command):
        # Parse the command as an AST (Abstract Syntax Tree)
        parsed_command = ast.parse(command.strip())

        # Check if the command contains an assignment node, print node, or import
        has_assignment = any(isinstance(node, ast.Assign) for node in ast.walk(parsed_command))
        has_print = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print' for node in ast.walk(parsed_command))
        has_import = any(isinstance(node, ast.Import) for node in ast.walk(parsed_command))
        is_assert = command.strip().startswith("assert")

        # Wrap the command with "print" if it's not an assignment and does not have a "print" statement
        if not any([has_assignment, has_print, has_import, is_assert]):
            return f"print({command})"
        else:
            return command
        
    def _input_multiline_function(self):
        lines = []
        while True:
            line = input(". ")
            if len(line) == 0:
                break
            lines.append(line)
        return "\n".join(lines)

    def execute_python_code(self, action: str) -> None:
        try:
            if action.strip().startswith("def "):
                function_definition = self._input_multiline_function()
                action = action + "\n" + function_definition
            else:
                action = self._wrap_with_print(action)
            logger.info(f"Command run: {action}")
            observation = self._execute_python_code(action)
        except Exception as err:
            observation = f"Error executing action: {err}"
        return observation

    def _inject_matplotlib_defaults(self, content: str) -> str:
        """
        Ensures rcParams are configured whenever matplotlib is imported as plt.
        """
        if self.language == "en":
            return content
        if not any(pattern in content for pattern in self._MATPLOTLIB_IMPORT_PATTERNS):
            return content
        missing_lines = [
            line for line in self._MATPLOTLIB_RC_LINES if line not in content
        ]
        if not missing_lines:
            return content

        lines = content.splitlines()
        for idx, line in enumerate(lines):
            if any(pattern in line for pattern in self._MATPLOTLIB_IMPORT_PATTERNS):
                indent = line[: len(line) - len(line.lstrip())]
                snippet = [indent + line for line in missing_lines]
                lines[idx + 1 : idx + 1] = snippet
                return "\n".join(lines)
        return content

    def _execute_python_code(self, code: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
            dir=str(self._real_work_dir),
        ) as temp_file:
            script_path = Path(temp_file.name)
            content = code
            if self.virtual_work_dir:
                content = content.replace(self.virtual_work_dir, str(self.root_dir))
            content = self._inject_matplotlib_defaults(content)
            temp_file.write(content)
        env = os.environ.copy()
        env.setdefault("LANG", "en_US.UTF-8")
        env.setdefault("LC_ALL", "en_US.UTF-8")
        env.setdefault("LC_CTYPE", "en_US.UTF-8")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if self._extra_pythonpath:
            env["PYTHONPATH"] = (
                f"{self._extra_pythonpath}:{env['PYTHONPATH']}"
                if "PYTHONPATH" in env and env["PYTHONPATH"]
                else self._extra_pythonpath
            )
        try:
            result = subprocess.run(
                ["python3", str(script_path)],
                cwd=str(self._real_work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                env=env,
            )
            output = result.stdout.strip()
            if result.returncode != 0 and not output:
                output = f"Python execution failed with exit code {result.returncode}"
            return output
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _setup_sitecustomize(self) -> None:
        if self.language == "en":
            return
        font_path = Path(self._SIMHEI_PATH)
        if not font_path.exists():
            logger.warning("SimHei font missing at %s; skipping sitecustomize setup.", font_path)
            return
        target = self._SITE_CUSTOMIZE
        target.parent.mkdir(parents=True, exist_ok=True)
        content = f"""# Auto-generated to register SimHei for matplotlib
from pathlib import Path
from matplotlib import font_manager, rcParams
fp = Path(r"{font_path}")
if fp.exists():
    font_manager.fontManager.addfont(str(fp))
    name = font_manager.FontProperties(fname=fp).get_name()
    rcParams['font.sans-serif'] = [name, 'SimHei']
    rcParams['font.family'] = 'sans-serif'
    rcParams['axes.unicode_minus'] = False
"""
        try:
            target.write_text(content, encoding="utf-8")
            self._extra_pythonpath = str(target.parent)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write sitecustomize for SimHei: %s", exc)
    
    def execute_command(self, command: str):
        adjusted_command = self._replace_virtual_paths(command)
        result = self._run_subprocess(adjusted_command)
        output = (result.stdout or "").strip()

        if result.returncode != 0 and not output:
            output = f"Command exited with status {result.returncode}"

        is_cd_flag = command.strip().startswith("cd ")
        if is_cd_flag:
            changed = command[command.index("cd ") + 3:].strip()
            if "&&" in changed:
                changed = changed[:changed.index("&&")].strip()
            if result.returncode == 0:
                self.work_dir = self.update_working_directory(self.work_dir, changed)
                self._real_work_dir = self._virtual_to_real(self.work_dir)
                return f"The command to change directory to {self.work_dir} is executed successfully."
            return output or f"Failed to change directory: exit status {result.returncode}"

        return output

    def _file_exists(self, file_path: str) -> bool:
        real_path = self.get_real_file_path(file_path)
        return real_path.is_file()
    
    def execute_python_file(self, file_path: str, content: str):
        real_path = self.get_real_file_path(file_path)
        real_path.parent.mkdir(parents=True, exist_ok=True)

        script_content = content
        if self.virtual_work_dir:
            script_content = script_content.replace(self.virtual_work_dir, str(self.root_dir))
        script_content = self._inject_matplotlib_defaults(script_content)

        real_path.write_text(script_content, encoding="utf-8")

        result = subprocess.run(
            ["python3", str(real_path)],
            cwd=str(self._real_work_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        output = (result.stdout or "").strip()
        if result.returncode != 0 and not output:
            output = f"Python execution failed with exit code {result.returncode}"
        return output
    
    def execute_sql_code(self,file_path, code, output: str) -> str:
        if code.startswith('""') and code.endswith('""'):
            code = code[2:-2]
        signature = (file_path, code, output or "direct")
        if (
            self._last_sql_signature == signature
            and self._consecutive_sql_errors >= self._sql_repeat_limit
        ):
            return (
                "ERROR: The same SQL command has failed multiple times. "
                "Please revise it before retrying."
            )

        script_content = LOCAL_SQL_TEMPLATE.format(
            file_path_literal=repr(file_path),
            sql_command_literal=repr(code),
            output_path_literal=repr(output or "direct"),
        )
        temp_file_path = "temp_sql_script.py"
        observation = self.execute_python_file(temp_file_path, script_content)
        temp_script_real = self.get_real_file_path(temp_file_path)
        try:
            temp_script_real.unlink(missing_ok=True)
        except Exception:
            pass
        if observation.startswith(f'File "{temp_file_path}"'):
            observation = observation.split("\n", 1)[1]

        normalized = (observation or "").strip()
        is_error = normalized.lower().startswith("error")
        is_error = is_error or normalized.lower().startswith("python execution failed")

        if signature == self._last_sql_signature:
            self._consecutive_sql_errors = (
                self._consecutive_sql_errors + 1 if is_error else 0
            )
        else:
            self._last_sql_signature = signature
            self._consecutive_sql_errors = 1 if is_error else 0

        return observation
    
    def execute_bq_exec_sql_query(self, action):
        sql_query, is_save = action.sql_query, action.is_save
        save_path = getattr(action, 'save_path', "")

        script_content = BQ_EXEC_SQL_QUERY_TEMPLATE.format(
            sql_query=sql_query, is_save=is_save, save_path=save_path)

        temp_file_path = "temp_sql_script.py" 
        observation = self.execute_python_file(temp_file_path, script_content)
        self.get_real_file_path(temp_file_path).unlink(missing_ok=True)
        if observation.startswith(f'File "{temp_file_path}"'):
            observation = observation.split("\n", 1)[1]
        return observation
    
    def execute_sf_exec_sql_query(self, action):
        sql_query, is_save = action.sql_query, action.is_save
        save_path = getattr(action, 'save_path', "")

        script_content = SF_EXEC_SQL_QUERY_TEMPLATE.format(
            sql_query=sql_query, is_save=is_save, save_path=save_path)

        temp_file_path = "temp_sql_script.py" 
        observation = self.execute_python_file(temp_file_path, script_content)
        self.get_real_file_path(temp_file_path).unlink(missing_ok=True)
        if observation.startswith(f'File "{temp_file_path}"'):
            observation = observation.split("\n", 1)[1]
        return observation
    
    def execute_sf_get_tables(self, action):
        database_name, schema_name, save_path = action.database_name, action.schema_name, action.save_path 
        script_content = SF_GET_TABLES_TEMPLATE.format(database_name=database_name, schema_name=schema_name, save_path=save_path)
        temp_file_path = "temp_sql_script.py" 
        observation = self.execute_python_file(temp_file_path, script_content)
        self.get_real_file_path(temp_file_path).unlink(missing_ok=True)
        if observation.startswith(f'File "{temp_file_path}"'):
            observation = observation.split("\n", 1)[1]
        return observation
    
    def execute_sf_get_table_info(self, action):
        database_name, schema_name, table, save_path = action.database_name, action.schema_name, action.table, action.save_path
        script_content = SF_GET_TABLE_INFO_TEMPLATE.format(
            database_name=database_name, schema_name=schema_name, table=table, save_path=save_path)
        temp_file_path = "temp_sql_script.py" 
        observation = self.execute_python_file(temp_file_path, script_content)
        self.get_real_file_path(temp_file_path).unlink(missing_ok=True)
        if observation.startswith(f'File "{temp_file_path}"'):
            observation = observation.split("\n", 1)[1]
        return observation
    
    def execute_sf_sample_rows(self, action):
        database_name, schema_name, table, row_number, save_path = action.database_name, action.schema_name, action.table, action.row_number, action.save_path
        script_content = SF_SAMPLE_ROWS_TEMPLATE.format(
            database_name=database_name, schema_name=schema_name, table=table, row_number=row_number, save_path=save_path)
        temp_file_path = "temp_sql_script.py" 
        observation = self.execute_python_file(temp_file_path, script_content)
        self.get_real_file_path(temp_file_path).unlink(missing_ok=True)
        if observation.startswith(f'File "{temp_file_path}"'):
            observation = observation.split("\n", 1)[1]
        return observation


    
    def execute_bq_get_tables(self, action):
        database_name, dataset_name, save_path = action.database_name, action.dataset_name, action.save_path 
        script_content = BQ_GET_TABLES_TEMPLATE.format(database_name=database_name, dataset_name=dataset_name, save_path=save_path)
        temp_file_path = "temp_sql_script.py" 
        observation = self.execute_python_file(temp_file_path, script_content)
        self.get_real_file_path(temp_file_path).unlink(missing_ok=True)
        if observation.startswith(f'File "{temp_file_path}"'):
            observation = observation.split("\n", 1)[1]
        return observation
    
    def execute_bq_get_table_info(self, action):
        database_name, dataset_name, table, save_path = action.database_name, action.dataset_name, action.table, action.save_path
        script_content = BQ_GET_TABLE_INFO_TEMPLATE.format(
            database_name=database_name, dataset_name=dataset_name, table=table, save_path=save_path)
        temp_file_path = "temp_sql_script.py" 
        observation = self.execute_python_file(temp_file_path, script_content)
        self.get_real_file_path(temp_file_path).unlink(missing_ok=True)
        if observation.startswith(f'File "{temp_file_path}"'):
            observation = observation.split("\n", 1)[1]
        return observation

    def execute_bq_sample_rows(self, action):
        database_name, dataset_name, table, row_number, save_path = action.database_name, action.dataset_name, action.table, action.row_number, action.save_path
        script_content = BQ_SAMPLE_ROWS_TEMPLATE.format(
            database_name=database_name, dataset_name=dataset_name, table=table, row_number=row_number, save_path=save_path)
        temp_file_path = "temp_sql_script.py" 
        observation = self.execute_python_file(temp_file_path, script_content)
        self.get_real_file_path(temp_file_path).unlink(missing_ok=True)
        if observation.startswith(f'File "{temp_file_path}"'):
            observation = observation.split("\n", 1)[1]
        return observation
    
    
    
    
    def create_file(self, file_path: str, content: str):
        real_path = self.get_real_file_path(file_path)
        if real_path.exists():
            return f"File {file_path} already exists."

        real_path.parent.mkdir(parents=True, exist_ok=True)
        real_path.write_text(content, encoding="utf-8")
        return ""

    def edit_file(self, file_path: str, content: str):
        real_path = self.get_real_file_path(file_path)

        if not real_path.exists():
            return f"File {file_path} does not exist."

        real_path.parent.mkdir(parents=True, exist_ok=True)
        real_path.write_text(content, encoding="utf-8")

        return ""

    
    def get_real_file_path(self, file_path: str):
        if isinstance(file_path, Path):
            file_path = str(file_path)

        if os.path.isabs(file_path):
            if self.virtual_work_dir and file_path.startswith(self.virtual_work_dir):
                remainder = file_path[len(self.virtual_work_dir):].lstrip("/")
                return (self.root_dir / remainder).resolve()
            return Path(file_path).resolve()

        normalized = file_path[2:] if file_path.startswith("./") else file_path
        return (self._real_work_dir / normalized).resolve()
    
    
    def get_current_workdir(self):
        return self.work_dir
    
    
    def update_working_directory(self, current: str, changed: Optional[str] = None) -> str:
        """ Resolves absolute path from the current working directory path and the argument of the `cd` command
        @args:
            current (str): the current working directory
            changed (Optional[str]): the changed working directory, argument of shell `cd` command
        @return:
            new_path (str): absolute path of the new working directory in the container
        """
        if not changed:
            return current
        if changed[0] == "/":
            current = ""

        path = []
        for segment in (current + "/" + changed).split("/"):
            if segment == "..":
                if path:
                    path.pop()
            elif segment and segment != ".":
                path.append(segment)
        new_path = "/" + "/".join(path)
        return new_path
