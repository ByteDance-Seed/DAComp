import logging
import os
import shutil
import uuid
from typing import Any, Dict, List

import requests

from spider_agent import configs

logger = logging.getLogger("spider_agent.setup")


class SetupController:
    def __init__(self, controller, cache_dir: str):
        self.controller = controller
        self.cache_dir = cache_dir
        self.mnt_dir = controller.root_dir.as_posix()
        self.virtual_work_dir = controller.virtual_work_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def setup(self, config: List[Dict[str, Any]]):
        """
        Args:
            config (List[Dict[str, Any]]): list of dict like {str: Any}. each
              config dict has the structure like
                {
                    "type": str, corresponding to the `_{:}_setup` methods of
                      this class
                    "parameters": dict like {str, Any} providing the keyword
                      parameters
                }
        """
        for cfg in config:
            config_type: str = cfg["type"]
            parameters: Dict[str, Any] = cfg["parameters"]

            setup_function: str = f"_{config_type}_setup"

            if hasattr(self, setup_function):
                getattr(self, setup_function)(**parameters)
                logger.info("SETUP: %s(%s)", setup_function, str(parameters))
            else:
                setup_function = f"{config_type}_setup"
                config_function = getattr(configs, setup_function, None)
                assert (
                    config_function is not None
                ), f"Setup controller cannot find function {setup_function}"
                config_function(self, **parameters)
                logger.info("SETUP: %s(%s)", setup_function, str(parameters))

    def _download_setup(self, files: List[Dict[str, str]]):
        """
        Args:
            files (List[Dict[str, str]]): files to download. list of dict like
              {
                "url": str, the url to download
                "path": str, the path in the workspace to store the downloaded file
              }
        """
        for f in files:
            url: str = f["url"]
            path: str = f["path"]

            if not url or not path:
                raise ValueError(
                    f"Setup Download - Invalid URL ({url}) or path ({path})."
                )

            cache_path = os.path.join(
                self.cache_dir,
                f"{uuid.uuid5(uuid.NAMESPACE_URL, url)}_{os.path.basename(path)}",
            )

            if not os.path.exists(cache_path):
                max_retries = 3
                downloaded = False
                last_error = None
                for i in range(max_retries):
                    try:
                        response = requests.get(url, stream=True, timeout=10)
                        response.raise_for_status()

                        with open(cache_path, "wb") as cache_file:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    cache_file.write(chunk)
                        logger.info("File downloaded successfully: %s", url)
                        downloaded = True
                        break
                    except requests.RequestException as exc:
                        last_error = exc
                        logger.error(
                            "Failed to download %s caused by %s. Retrying... (%d attempts left)",
                            url,
                            exc,
                            max_retries - i - 1,
                        )
                if not downloaded:
                    raise requests.RequestException(
                        f"Failed to download {url}. No retries left. Error: {last_error}"
                    )

            target_path = self.controller.get_real_file_path(path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(cache_path, target_path)

    def _execute_setup(self, command: str):
        """
        Execute setup command inside the workspace.
        """
        return self.controller.execute_command(command)
