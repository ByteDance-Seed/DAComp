#!/usr/bin/env python3
"""
DE-D evaluation script for data engineering and data architecture tasks.
"""

import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import re

import openai
from utils.eval_prompt import eval_prompt, eval_prompt_zh
from utils.config import (
    SUPPORTED_MODELS,
    DEFAULT_RESULTS_DIR,
    DEFAULT_GOLD_EN_JSONL,
    DEFAULT_GOLD_ZH_JSONL,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DEDEvaluator:
    """DE-D evaluator"""
    
    def __init__(
        self,
        eval_model: str = "default_eval_config",
        project_path: str = None,
        results_dir: str = str(DEFAULT_RESULTS_DIR),
        gold_en_jsonl: str = str(DEFAULT_GOLD_EN_JSONL),
        gold_zh_jsonl: str = str(DEFAULT_GOLD_ZH_JSONL),
        max_workers: int = 4,
        use_fast_api: bool = True
    ):
        self.eval_model = eval_model  
        self.max_workers = max_workers  
        self.use_fast_api = use_fast_api 
        self.gold_en_jsonl = Path(gold_en_jsonl)
        self.gold_zh_jsonl = Path(gold_zh_jsonl)
        self.results_dir = Path(results_dir)

        if project_path:
            self.project_path = Path(project_path)
            if not self.project_path.exists():
                raise ValueError(f"Project path does not exist: {project_path}")
        else:
            self.project_path = None

        if project_path:
            project_name = Path(project_path).name
        else:
            project_name = "default"

        self.project_name = project_name
        self.output_dir = Path("evaluation_results") / project_name
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.lock = threading.Lock()

        self.gold_en_map = self._load_gold_jsonl(self.gold_en_jsonl)
        self.gold_zh_map = self._load_gold_jsonl(self.gold_zh_jsonl)
        self.gold_ids = set(self.gold_en_map.keys()) | set(self.gold_zh_map.keys())

    def _load_gold_jsonl(self, path: Path) -> Dict[str, Dict[str, str]]:
        if not path.exists():
            return {}
        data = {}
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                task_id = obj.get("id")
                if task_id:
                    data[task_id] = {
                        "question": obj.get("question", ""),
                        "rubric": obj.get("rubric", "")
                    }
        return data

    def _select_gold(self, task_name: str, project_path: str):
        is_zh = task_name.endswith("-zh") or "arch-zh" in str(project_path)
        gold_map = self.gold_zh_map if is_zh else self.gold_en_map
        if task_name not in gold_map and not is_zh and f"{task_name}-zh" in self.gold_zh_map:
            gold_map = self.gold_zh_map
            is_zh = True
        if task_name not in gold_map:
            raise FileNotFoundError(f"Gold question/rubric not found for task {task_name}")
        return gold_map, is_zh

    def _list_tasks_in_dir(self, project_dir: Path) -> List[str]:
        tasks: List[str] = []
        if not project_dir.exists():
            logger.error(f"Project directory does not exist: {project_dir}")
            return tasks
        for yaml_file in project_dir.glob("*.yaml"):
            task_name = yaml_file.stem
            if task_name in self.gold_ids:
                tasks.append(task_name)
            else:
                logger.warning(f"Task {task_name} missing corresponding gold (not found in gold jsonl)")
        return tasks


    def load_blueprint_from_results(self, project_path: str, task_name: str) -> str:
        """Load blueprint yaml for the task from the project directory."""
        blueprint_path = Path(project_path) / f"{task_name}.yaml"

        try:
            with open(blueprint_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load blueprint: {blueprint_path}, error: {e}")
            raise

    def extract_max_score_from_rubric(self, rubric_content: str) -> int:
        """Extract maximum total score (supports CN/EN phrasing)."""
        lines = rubric_content.split('\n')
        for line in lines:
            if '总分' in line and '分' in line:
                match = re.search(r'总分.*?(\d+)', line)
                if match:
                    return int(match.group(1))
            if 'Total Score' in line:
                match = re.search(r'Total Score[^0-9]*?(\d+)', line, re.IGNORECASE)
                if match:
                    return int(match.group(1))
        return 0
        
    def call_llm_api(self, prompt: str, model_name: str, max_retries: int = 5) -> str:
        """Call LLM API with retries."""
        import time
        import random

        for attempt in range(max_retries):
            try:
                if model_name not in SUPPORTED_MODELS:
                    raise ValueError(f"Unsupported model: {model_name}")

                config = SUPPORTED_MODELS[model_name]

                client = openai.AzureOpenAI(
                    azure_endpoint=config["base_url"],
                    api_version=config["api_version"],
                    api_key=config["api_key"],
                    timeout=300  
                )

                api_params = {
                    "model": model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": prompt
                                }
                            ]
                        }
                    ],
                    "max_tokens": config["max_tokens"],
                    "extra_headers": {"X-TT-LOGID": ""},
                }

                # Special handling for specific models (align with run.py)
                if model_name == "openai_qwen3-235b-a22b" or model_name == "openai_qwen3-8b":
                    api_params["extra_body"] = {
                        "stream": False,
                        "enable_thinking": False
                    }

                completion = client.chat.completions.create(**api_params)
                return completion.choices[0].message.content

            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    wait_time = (2 ** attempt) + random.uniform(0, 1) 
                    with self.lock:
                        logger.warning(f"API rate limited, retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                elif "token limit" in str(e).lower():
                    with self.lock:
                        logger.error(f"Token limit error, not retrying: {e}")
                    return None
                else:
                    with self.lock:
                        logger.error(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        return None
                    time.sleep(1) 

        return None

    def evaluate_single_task(self, project_path: str, task_name: str) -> Dict[str, Any]:
        """Evaluate a single task."""
        with self.lock:
            logger.info(f"Start evaluating task: {project_path}/{task_name}")

        gold_map, is_zh = self._select_gold(task_name, project_path)

        blueprint_content = self.load_blueprint_from_results(project_path, task_name)
        question_content = gold_map[task_name]["question"]
        rubric_content = gold_map[task_name]["rubric"]

        max_score = self.extract_max_score_from_rubric(rubric_content)

        prompt_tpl = eval_prompt_zh if is_zh else eval_prompt
        formatted_prompt = prompt_tpl.format(
            user_query=question_content,
            model_blueprint=blueprint_content,
            rubric=rubric_content
        )

        with self.lock:
            logger.info(f"Calling LLM: {project_path}/{task_name}...")

        try:
            response_content = self.call_llm_api(formatted_prompt, self.eval_model)

            if response_content is None:
                raise Exception("LLM call failed")

            evaluation_result = self.parse_evaluation_result(response_content)

            result = {
                "task_name": task_name,
                "project_path": project_path,
                "timestamp": datetime.now().isoformat(),
                "eval_model": self.eval_model,
                "max_score": max_score,
                "evaluation": evaluation_result,
                "raw_response": response_content
            }
            actual_score = self.extract_actual_score(evaluation_result)
            result["actual_score"] = actual_score

            with self.lock:
                logger.info(f"Task {project_path}/{task_name} evaluated, score: {actual_score}/{max_score}")
            return result

        except Exception as e:
            with self.lock:
                logger.error(f"Error evaluating task {project_path}/{task_name}: {e}")
            return {
                "task_name": task_name,
                "project_path": project_path,
                "timestamp": datetime.now().isoformat(),
                "eval_model": self.eval_model,
                "max_score": max_score,
                "error": str(e),
                "actual_score": 0
            }

    def parse_evaluation_result(self, response_content: str) -> Dict[str, Any]:
        """Parse JSON section from the LLM response."""
        try:
            json_match = re.search(r'```json\s*\n(.*?)\n```', response_content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                return json.loads(json_str)
            else:
                return json.loads(response_content)
        except json.JSONDecodeError as e:
            logger.warning(f"Could not parse JSON response: {e}")
            return {"parse_error": str(e), "raw_content": response_content}

    def extract_actual_score(self, evaluation_result: Dict[str, Any]) -> int:
        """Extract actual score from evaluation result (retains CN keys)."""
        if "总得分" in evaluation_result:
            return evaluation_result["总得分"]
        elif "parse_error" not in evaluation_result:
            total_score = 0
            for value in evaluation_result.values():
                if isinstance(value, dict) and "总得分" in value:
                    total_score += value["总得分"]
            return total_score
        return 0

    def save_task_result(self, result: Dict[str, Any]) -> str:
        """Save evaluation result for a single task."""
        task_name = result["task_name"]
        result_file = self.output_dir / f"{task_name}_evaluation.json"

        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        with self.lock:
            logger.info(f"Saved evaluation result: {result_file}")
        return str(result_file)

    def create_summary(self, all_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create summary across tasks."""
        summary = {
            "timestamp": datetime.now().isoformat(),
            "total_tasks": len(all_results),
            "eval_model": self.eval_model,
            "project_name": "unknown", 
            "tasks": []
        }

        total_actual_score = 0
        total_max_score = 0

        for result in all_results:
            task_summary = {
                "task_name": result["task_name"],
                "actual_score": result.get("actual_score", 0),
                "max_score": result.get("max_score", 0),
                "success": "error" not in result
            }

            total_actual_score += task_summary["actual_score"]
            total_max_score += task_summary["max_score"]

            summary["tasks"].append(task_summary)

        summary["total_actual_score"] = total_actual_score
        summary["total_max_score"] = total_max_score
        summary["overall_score_rate"] = total_actual_score / total_max_score if total_max_score > 0 else 0

        return summary

    def save_summary(self, summary: Dict[str, Any]) -> str:
        """Save summary file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        summary_file = self.output_dir / f"evaluation_summary_{timestamp}.json"

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved summary to: {summary_file}")
        return str(summary_file)

    
    def find_all_tasks(self, project_path: str = None) -> List[str]:
        target_dir = Path(project_path) if project_path else (self.project_path or (self.results_dir / self.project_name))
        return self._list_tasks_in_dir(target_dir)

    def list_all_projects(self) -> List[str]:
        projects = []
        if self.results_dir.exists():
            for project_dir in self.results_dir.iterdir():
                if project_dir.is_dir() and list(project_dir.glob("*.yaml")):
                    projects.append(str(project_dir))
        return sorted(projects)

    def evaluate_all_projects(self, project_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        if project_paths is None:
            project_paths = self.list_all_projects()

        if not project_paths:
            raise ValueError("No projects found for evaluation")

        logger.info(f"Start evaluating {len(project_paths)} project(s)")
        all_results = {}
        project_scores = []

        for project_path in project_paths:
            try:
                logger.info(f"Evaluating project: {project_path}")

                project_evaluator = DEDEvaluator(
                    eval_model=self.eval_model,
                    project_path=project_path,
                    rubric_dir=str(self.rubric_dir),
                    max_workers=self.max_workers
                )

                tasks = project_evaluator.find_all_tasks(project_path)
                if tasks:
                    summary_file = project_evaluator.evaluate_all(tasks)

                    with open(summary_file, 'r', encoding='utf-8') as f:
                        summary = json.load(f)

                    project_score = {
                        "project_path": project_path,
                        "project_name": Path(project_path).name,
                        "task_count": summary.get("total_tasks", 0),
                        "total_actual_score": summary.get("total_actual_score", 0),
                        "total_max_score": summary.get("total_max_score", 0),
                        "overall_score_rate": summary.get("overall_score_rate", 0),
                        "eval_model": summary.get("eval_model", self.eval_model),
                        "summary_file": summary_file,
                        "status": "success"
                    }

                    all_results[project_path] = project_score
                    project_scores.append(project_score)
                else:
                    project_score = {
                        "project_path": project_path,
                        "project_name": Path(project_path).name,
                        "task_count": 0,
                        "total_actual_score": 0,
                        "total_max_score": 0,
                        "overall_score_rate": 0,
                        "eval_model": self.eval_model,
                        "status": "no_tasks",
                        "message": "No tasks found for evaluation"
                    }
                    all_results[project_path] = project_score
                    project_scores.append(project_score)

            except Exception as e:
                logger.error(f"Failed to evaluate project {project_path}: {e}")
                project_score = {
                    "project_path": project_path,
                    "project_name": Path(project_path).name,
                    "task_count": 0,
                    "total_actual_score": 0,
                    "total_max_score": 0,
                    "overall_score_rate": 0,
                    "eval_model": self.eval_model,
                    "status": "error",
                    "error": str(e)
                }
                all_results[project_path] = project_score
                project_scores.append(project_score)

        project_scores.sort(key=lambda x: x["overall_score_rate"], reverse=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        all_projects_summary_file = Path("evaluation_results") / f"all_projects_summary_{timestamp}.json"
        all_projects_summary_file.parent.mkdir(parents=True, exist_ok=True)

        all_projects_summary = {
            "timestamp": datetime.now().isoformat(),
            "eval_model": self.eval_model,
            "total_projects": len(project_paths),
            "successful_projects": len([p for p in project_scores if p["status"] == "success"]),
            "project_scores": project_scores,
            "rankings": {
                "by_score_rate": [p["project_name"] for p in project_scores],
                "by_total_score": sorted(project_scores, key=lambda x: x["total_actual_score"], reverse=True)
            }
        }

        with open(all_projects_summary_file, 'w', encoding='utf-8') as f:
            json.dump(all_projects_summary, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved all-projects summary to: {all_projects_summary_file}")

        return {
            "timestamp": datetime.now().isoformat(),
            "eval_model": self.eval_model,
            "total_projects": len(project_paths),
            "all_projects_summary_file": str(all_projects_summary_file),
            "project_scores": project_scores,
            "results": all_results
        }

    def evaluate_all(self, task_names: Optional[List[str]] = None) -> str:
        """Evaluate all or selected tasks (supports parallel execution)."""
        if task_names is None:
            task_names = self.find_all_tasks()

        if not task_names:
            raise ValueError("No tasks found for evaluation")

        logger.info(f"Start evaluating {len(task_names)} task(s): {task_names}")
        logger.info(f"Using {self.max_workers} worker(s)")

        all_results = []

        current_project_path = str(self.project_path or self.results_dir)
        project_name = Path(current_project_path).name

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {
                executor.submit(self.evaluate_single_task, current_project_path, task_name): task_name
                for task_name in task_names
            }

            for future in as_completed(future_to_task):
                task_name = future_to_task[future]
                try:
                    result = future.result()
                    all_results.append(result)
                    self.save_task_result(result)
                except Exception as e:
                    logger.error(f"Failed to evaluate task {task_name}: {e}")
                    error_result = {
                        "task_name": task_name,
                        "project_path": current_project_path,
                        "project_name": project_name,
                        "timestamp": datetime.now().isoformat(),
                        "eval_model": self.eval_model,
                        "error": str(e),
                        "actual_score": 0,
                        "max_score": 0
                    }
                    all_results.append(error_result)
                    self.save_task_result(error_result)

        summary = self.create_summary(all_results)

        current_project = str(self.project_path or self.results_dir)
        summary["project_name"] = Path(current_project).name
        summary_file = self.save_summary(summary)

        logger.info("="*50)
        logger.info("Evaluation summary:")
        logger.info(f"Project: {summary['project_name']}")
        logger.info(f"Total tasks: {summary['total_tasks']}")
        logger.info(f"Total score: {summary['total_actual_score']}/{summary['total_max_score']}")
        logger.info(f"Score rate: {summary['overall_score_rate']:.2%}")
        logger.info("="*50)

        return summary_file


def collect_model_dirs(base_path: Path) -> List[Path]:
    """Return model directories to evaluate.

    If base_path contains yaml files, treat it as a single model dir.
    Otherwise, return immediate subdirectories that contain yaml files.
    """
    if list(base_path.glob("*.yaml")):
        return [base_path]
    model_dirs: List[Path] = []
    if base_path.exists():
        for sub in base_path.iterdir():
            if sub.is_dir() and list(sub.glob("*.yaml")):
                model_dirs.append(sub)
    return sorted(model_dirs)


def main():
    parser = argparse.ArgumentParser(description="DE-Arch evaluator (supports Chinese/English tasks)")
    parser.add_argument("--task", type=str, help="Evaluate a single task ID")
    parser.add_argument("--tasks", type=str, nargs="+", help="Evaluate multiple task IDs")
    parser.add_argument("--all", action="store_true", help="Evaluate all tasks in the directory")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash", choices=list(SUPPORTED_MODELS.keys()), help="LLM model for evaluation (default: gemini-2.5-flash)")
    parser.add_argument("--project-path", type=str, required=True, help="Model directory or experiment root containing model directories")
    parser.add_argument("--gold-en-jsonl", type=str, default=str(DEFAULT_GOLD_EN_JSONL), help="English gold (question/rubric) JSONL path")
    parser.add_argument("--gold-zh-jsonl", type=str, default=str(DEFAULT_GOLD_ZH_JSONL), help="Chinese gold (question/rubric) JSONL path")
    parser.add_argument("--max-workers", type=int, default=10, help="Max parallel workers")
    parser.add_argument("--list-models", action="store_true", help="List supported evaluator models")

    args = parser.parse_args()
    eval_model = args.model

    if args.list_models:
        print("📋 Supported evaluator models:")
        for model, config in SUPPORTED_MODELS.items():
            print(f"  - {model}: max_tokens={config['max_tokens']}")
        return 0

    base_path = Path(args.project_path).resolve()
    if not base_path.exists():
        print(f"Error: path does not exist {base_path}")
        return 1

    model_dirs = collect_model_dirs(base_path)
    if not model_dirs:
        print(f"Error: no model directories with yaml found under {base_path}")
        return 1

    for model_dir in model_dirs:
        print(f"▶️  Evaluating model directory: {model_dir}")
        evaluator = DEDEvaluator(
            eval_model=eval_model,
            project_path=str(model_dir),
            results_dir=str(DEFAULT_RESULTS_DIR),
            gold_en_jsonl=args.gold_en_jsonl,
            gold_zh_jsonl=args.gold_zh_jsonl,
            max_workers=args.max_workers
        )

        available = evaluator.find_all_tasks(str(model_dir))

        if args.task:
            selected = [args.task]
        elif args.tasks:
            selected = args.tasks
        else:
            selected = available

        if not selected:
            print(f"  ⚠️  No tasks found to evaluate in: {model_dir}")
            continue

        if args.task:
            result = evaluator.evaluate_single_task(str(model_dir), selected[0])
            evaluator.save_task_result(result)
            print(f"  Task {selected[0]} score: {result.get('actual_score', 0)}/{result.get('max_score', 0)}")
        else:
            summary_file = evaluator.evaluate_all(selected)
            print(f"  Summary saved: {summary_file}")

    return 0


if __name__ == "__main__":
    exit(main())
