import logging
import os
import signal
import sys
import time
from typing import Any, Dict, Optional, Union, Callable

import gymnasium as gym

from spider_agent.controllers.python import PythonController
from spider_agent.controllers.setup import SetupController
from spider_agent.envs.utils import (
    calculate_sha256,
    create_folder_if_not_exists,
    delete_files_in_folder,
    is_file_valid,
    timeout,
)
from spider_agent import configs
from spider_agent.agent.action import (
    Action,
    Bash,
    Terminate,
    CreateFile,
    EditFile,
    LOCAL_DB_SQL,
    BIGQUERY_EXEC_SQL,
    BQ_GET_TABLES,
    BQ_GET_TABLE_INFO,
    BQ_SAMPLE_ROWS,
)
from spider_agent.agent.action import (
    SNOWFLAKE_EXEC_SQL,
    SF_GET_TABLES,
    SF_GET_TABLE_INFO,
    SF_SAMPLE_ROWS,
)

logger = logging.getLogger("spider_agent.env")

Metric = Callable[[Any, Any], float]
Getter = Callable[[gym.Env, Dict[str, Any]], Any]


# constants
DEFAULT_TIME_OUT = 300  # default waiting time for each action
MAX_OBS_LENGTH = 60000
EMPTY_DATA_PATH = "spider_agent/data/empty"  # an empty data directory
DEFAULT_WORK_DIR = "/workspace"  # default working directory (logical)
DEFAULT_MNT_DIR = (
    "spider_agent/mnt"  # default directory to copy and mount data path, also the output directory
)
TASK_FINISHED = "task_finished"  # infos key
ACTION_EXEC = "action_executed"  # infos key


class Spider_Agent_Env(gym.Env):
    """
    DesktopEnv with OpenAI Gym interface.
    Fixme: refactor the logic when implementing the multi-process version
    """
    def __init__(self, env_config, task_config, cache_dir, mnt_dir):
        """
        Args:
            task_config (Dict[str, Any]): manages task configs integratedly,
              including
              * base snapshot
              * task id (uuid)
              * instruction
              * setup config
        """
        super().__init__()
        self.task_config = task_config
        self.cache_dir_base = cache_dir
        self.env_name = env_config["init_args"].get("name", "spider_agent")
        self.mnt_dir = os.path.abspath(mnt_dir)
        self.virtual_work_dir = env_config["init_args"].get("work_dir", DEFAULT_WORK_DIR)
        self.work_dir = self.virtual_work_dir
        self.kwargs = env_config["init_args"]
        self.language = (self.kwargs.get("language") or "zh").lower()

        self._set_task_info(task_config)
        logger.info("Initializing...")
        self._prepare_workspace()

        self.controller = PythonController(
            root_dir=self.mnt_dir,
            virtual_work_dir=self.virtual_work_dir,
            language=self.language,
        )
        self.setup_controller = SetupController(
            controller=self.controller, cache_dir=self.cache_dir
        )

        logger.info("Setting up environment...")

        self.setup_controller.setup(self.config)
        self.init_files_hash = self._get_env_files_hash()
        time.sleep(0.1)
        logger.info("Environment setup complete.")

        signal.signal(signal.SIGINT, self._cleanup)
        signal.signal(signal.SIGTERM, self._cleanup)

    def _set_task_info(self, task_config: Dict[str, Any]):
        self.task_id: str = task_config["instance_id"]
        self.cache_dir: str = os.path.join(self.cache_dir_base, self.task_id)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.instruction = task_config["instruction"]

        self.config = task_config["config"] if "config" in task_config else []
        self.post_process_func = (
            task_config["post_process"] if "post_process" in task_config else []
        )

    def _cleanup_database_files(self):
        """Remove .duckdb and .sqlite files from the container working directory"""
        try:
            removed = 0
            for root, _dirs, files in os.walk(self.mnt_dir):
                for file in files:
                    if file.endswith(".duckdb") or file.endswith(".sqlite"):
                        file_path = os.path.join(root, file)
                        try:
                            os.remove(file_path)
                            removed += 1
                        except OSError as exc:
                            logger.warning("Failed to remove database file %s: %s", file_path, exc)
            if removed:
                logger.info("Removed %d database cache files.", removed)
        except Exception as exc:
            logger.warning("Error during database files cleanup: %s", exc)

    def close(self):
        self._cleanup_database_files()
        logger.info("Environment %s cleaned up.", self.env_name)

    def _cleanup(self, signum, frame):
        try:
            self._cleanup_database_files()
        except Exception:
            pass
        sys.exit(0)

    def _prepare_workspace(self):
        create_folder_if_not_exists(self.mnt_dir)
        delete_files_in_folder(self.mnt_dir)

    def _get_env_files_hash(self) -> Dict[str, str]:
        """
        Returns:
            Dict[str, str]: a dictionary of the hash of the files in the
              environment
        """
        files_hash = {}
        for root, dirs, files in os.walk(self.mnt_dir):
            for f in files:
                file_path = os.path.join(root, f)
                # Skip .duckdb and .sqlite files
                if file_path.endswith('.duckdb') or file_path.endswith('.sqlite'):
                    continue
                files_hash[file_path] = calculate_sha256(file_path)
        return files_hash
    

    def post_process(self):
        """
        Evaluate whether the task is successfully completed.
        """
        diff_files = self._find_diff_files_init(self.init_files_hash)

        post_process_files = []
        errors = []
        for post_process_f in self.post_process_func:
            process_function = getattr(configs, post_process_f, None)
            post_files, error = process_function(self.mnt_dir, self.controller)
            post_files = post_files if isinstance(post_files, list) else list(post_files)
            post_process_files.extend(post_files)
            errors.append(error)

        return {**diff_files, "post_process_files": post_process_files, "error": errors}

    def _find_diff_files_init(self, init_file_dict)-> Dict:
        init_file_paths = init_file_dict.keys()
        added_files_list = []
        changed_files_list = []
        for root, dirs, files in os.walk(self.mnt_dir):
            for f in files:
                file_path = os.path.join(root, f)
                # Skip .duckdb and .sqlite files
                if file_path.endswith('.duckdb') or file_path.endswith('.sqlite'):
                    continue
                if file_path not in init_file_paths:
                    added_files_list.append(file_path)
                else:
                    if init_file_dict[file_path] != calculate_sha256(file_path):
                        changed_files_list.append(file_path)
        return {"added_files": added_files_list, "changed_files": changed_files_list}

    
    def step(self, action: Action):
        try:
            with timeout(DEFAULT_TIME_OUT,"Action execution time exceeded!"):
                done = False
                if isinstance(action, Bash):
                    observation = self.execute_code_action(action)
                elif isinstance(action, BQ_GET_TABLES):
                    observation = self.controller.execute_bq_get_tables(action)
                elif isinstance(action, BQ_GET_TABLE_INFO):
                    observation = self.controller.execute_bq_get_table_info(action)
                elif isinstance(action, BQ_SAMPLE_ROWS):
                    observation = self.controller.execute_bq_sample_rows(action)
                elif isinstance(action, BIGQUERY_EXEC_SQL):
                    observation = self.controller.execute_bq_exec_sql_query(action)
                elif isinstance(action, LOCAL_DB_SQL):
                    observation = self.execute_sql_action(action)
                elif isinstance(action, SNOWFLAKE_EXEC_SQL):
                    observation = self.controller.execute_sf_exec_sql_query(action)
                elif isinstance(action, SF_GET_TABLES):
                    observation = self.controller.execute_sf_get_tables(action)
                elif isinstance(action, SF_GET_TABLE_INFO):
                    observation = self.controller.execute_sf_get_table_info(action)
                elif isinstance(action, SF_SAMPLE_ROWS):
                    observation = self.controller.execute_sf_sample_rows(action)
                elif isinstance(action, CreateFile):
                    observation = self.create_file_action(action)
                elif isinstance(action, EditFile):
                    observation = self.edit_file_action(action)
                elif isinstance(action, Terminate):
                    observation = "Terminate"
                    done = True
                else:
                    raise ValueError(f"Unrecognized action type {action.action_type} !")
        except TimeoutError as e:
            observation = str(e)
        
        observation = self._handle_observation(observation)
        # logger.info("Observation: %s", observation)
        return observation, done
    
    def _handle_observation(self, observation):
        max_length = MAX_OBS_LENGTH
        if len(observation) > max_length:
            truncated_observation = observation[:max_length] + "\n[Observation too long, truncated; Try other commands to get the left part.]"
            return truncated_observation
        return observation


    def execute_code_action(self, action: Bash):
        """ Execute action in bash shell """
        
        obs = self.controller.execute_command(action.code)
        if obs is None or obs == '':
            obs = "Command executed successfully. No output."
        
        return obs

    
    def execute_sql_action(self, action: LOCAL_DB_SQL):
        """ Execute action in sql"""
        obs = self.controller.execute_sql_code(action.file_path, action.code, action.output)
        if obs is None or obs == '':
            obs = f"SQL command executed successfully. No output."
        
        return obs
    
    def create_file_action(self, action: CreateFile):
        obs = self.controller.create_file(action.filepath, action.code)
        if obs is None or obs == '':
            real_file_path = self.controller.get_real_file_path(action.filepath)
            valid, error = is_file_valid(real_file_path)
            if valid:
                obs = f"File {action.filepath} created and written successfully."
            else:
                obs = f"Falied to validate file {action.filepath}, error: {error}"
        return obs
    
    def edit_file_action(self, action: EditFile):
        obs = self.controller.edit_file(action.filepath, action.code)
        if obs is None or obs == '':
            real_file_path = self.controller.get_real_file_path(action.filepath)
            valid, error = is_file_valid(real_file_path)
            if valid:
                obs = f"File {action.filepath} edited successfully."
            else:
                obs = f"Falied to validate file {action.filepath}, error: {error}"
        return obs
    
    
    
    def execute_tmp_action(self, action: Union[BQ_GET_TABLES, BQ_GET_TABLE_INFO, BQ_SAMPLE_ROWS]):
        """ Execute action in sql"""
        obs = self.controller.execute_sql_code(action.file_path, action.code, action.output)
        if obs is None or obs == '':
            obs = f"SQL command executed successfully. No output."
        
        return obs
    
