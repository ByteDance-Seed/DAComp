import base64
import json
import logging
import os
import re
import time
import uuid
from http import HTTPStatus
from io import BytesIO
from typing import Dict, List
from spider_agent.agent.prompts import DACOMP_SYSTEM_DESIGN, DACOMP_SYSTEM_DESIGN_IMAGE, DACOMP_SYSTEM_DESIGN_EN, DACOMP_SYSTEM_DESIGN_IMAGE_EN
from spider_agent.agent.action import Action, Bash, Terminate, CreateFile, EditFile, LOCAL_DB_SQL, BIGQUERY_EXEC_SQL, SNOWFLAKE_EXEC_SQL, BQ_GET_TABLES, BQ_GET_TABLE_INFO, BQ_SAMPLE_ROWS, SF_GET_TABLES, SF_GET_TABLE_INFO, SF_SAMPLE_ROWS
from spider_agent.envs.spider_agent import Spider_Agent_Env
from spider_agent.agent.models import call_llm


from openai import AzureOpenAI
from typing import Dict, List, Optional, Tuple, Any, TypedDict




logger = logging.getLogger("spider_agent")


class PromptAgent:
    def __init__(
        self,
        model="gpt-4",
        max_tokens=1500,
        top_p=0.9,
        temperature=0.5,
        max_memory_length=10,
        max_steps=15,
        use_plan=False,
        use_image_prompt: bool = False,
        language: str = "zh"
    ):
        
        self.model = model
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.max_memory_length = max_memory_length
        self.max_steps = max_steps
        
        self.thoughts = []
        self.responses = []
        self.actions = []
        self.observations = []
        self.system_message = ""
        self.history_messages = []
        self.env = None
        self.codes = []
        self.work_dir = "/workspace"
        self.use_plan = use_plan
        self.use_image_prompt = use_image_prompt
        self.language = language.lower() if language else "zh"
        self._last_repetition_signature = None
        
    def set_env_and_task(self, env: Spider_Agent_Env):
        self.env = env
        self.thoughts = []
        self.responses = []
        self.actions = []
        self.observations = []
        self.codes = []
        self.history_messages = []
        self.instruction = self.env.task_config['instruction']
        self._last_repetition_signature = None
        if 'plan' in self.env.task_config:
            self.reference_plan = self.env.task_config['plan']
        


        

        self._AVAILABLE_ACTION_CLASSES = [Bash, Terminate, CreateFile, EditFile, LOCAL_DB_SQL]
        action_space_parts = []
        for action_cls in self._AVAILABLE_ACTION_CLASSES:
            try:
                action_space_parts.append(action_cls.get_action_description(language=self.language))
            except TypeError:
                action_space_parts.append(action_cls.get_action_description())
        action_space = "".join(action_space_parts)

        # if self.env.task_config['type'] == 'creation':
        #     self.system_message = DACOMP_SYSTEM_CREATION.format(work_dir=self.work_dir, action_space=action_space, task=self.instruction, max_steps=self.max_steps)
        # elif self.env.task_config['type'] == 'evolution':
        #     self.system_message = DACOMP_SYSTEM_EVOLUTION.format(work_dir=self.work_dir, action_space=action_space, task=self.instruction, max_steps=self.max_steps)
        # elif self.env.task_config['type'] == 'design':
        #     self.system_message = DACOMP_SYSTEM_DESIGN.format(work_dir=self.work_dir, action_space=action_space, task=self.instruction, max_steps=self.max_steps)

        if self.use_image_prompt:
            prompt_template = DACOMP_SYSTEM_DESIGN_IMAGE_EN if self.language == "en" else DACOMP_SYSTEM_DESIGN_IMAGE
        else:
            prompt_template = DACOMP_SYSTEM_DESIGN_EN if self.language == "en" else DACOMP_SYSTEM_DESIGN

        self.system_message = prompt_template.format(work_dir=self.work_dir, action_space=action_space, task=self.instruction, max_steps=self.max_steps)
        

        self.history_messages.append({
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": self.system_message 
                },
            ]
        })
        
    def predict(self, obs: Dict=None) -> List:
        """
        Predict the next action(s) based on the current observation.
        """    
        
        assert len(self.observations) == len(self.actions) and len(self.actions) == len(self.thoughts) \
            , "The number of observations and actions should be the same."

        status = False
        while not status:
            messages = self.history_messages.copy()
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Observation: {}\n".format(str(obs))
                    }
                ]
            })  
            status, response = call_llm({
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "top_p": self.top_p,
                "temperature": self.temperature
            })

            response = response.strip()
            if not status:
                if response in ["context_length_exceeded","rate_limit_exceeded","max_tokens","unknown_error"]:
                    self.history_messages = [self.history_messages[0]] + self.history_messages[3:]
                else:
                    raise Exception(f"Failed to call LLM, response: {response}")
            
        try:
            action = self.parse_action(response)
            thought = re.search(r'Thought:(.*?)Action', response, flags=re.DOTALL)
            if thought:
                thought = thought.group(1).strip()
            else:
                thought = response
        except Exception as e:
            logger.error("Failed to parse action from response: %s", e)
            logger.debug("Response content: %s", response)
            action = None
        
        logger.info("Observation: %s", obs)
        logger.info("Response: %s", response)

        # 只有当action解析成功时才添加到历史记录
        if action is not None:
            self._add_message(obs, thought, action)
            self.observations.append(obs)
            self.thoughts.append(thought)
            self.responses.append(response)
            self.actions.append(action)
            self._maybe_warn_repeated_action()
        else:
            # 解析失败时，只记录response用于错误提示，不污染对话历史
            self.responses.append(response)


        # action is None
        
        return response, action
        
    
    def _add_message(self, observations: str, thought: str, action: Action):
        self.history_messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Observation: {}".format(observations)
                }
            ]
        })
        self.history_messages.append({
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "Thought: {}\n\nAction: {}".format(thought, str(action))
                }
            ]
        })
        if len(self.history_messages) > self.max_memory_length*2+1:
            # 保留系统消息(index 0) + 前5个step的消息(index 1-10) + 最近的消息
            system_msg = self.history_messages[0]
            first_5_steps = self.history_messages[1:11]  # 前5个step = 10条消息(每step 2条)
            recent_msgs = self.history_messages[-(self.max_memory_length*2-10):] if len(self.history_messages) > 11 else []
            self.history_messages = [system_msg] + first_5_steps + recent_msgs
    
    def _action_signature(self, action: Action) -> str:
        """
        Create a stable signature string for an action so we can detect repeats.
        """
        try:
            return f"{action.__class__.__name__}:{json.dumps(action.__dict__, sort_keys=True, default=str, ensure_ascii=False)}"
        except Exception:
            return str(action)

    def _maybe_warn_repeated_action(self):
        if len(self.actions) < 3:
            self._last_repetition_signature = None
            return
        last_three = [self._action_signature(a) for a in self.actions[-3:]]
        if last_three[0] == last_three[1] == last_three[2]:
            signature = last_three[0]
            if signature == self._last_repetition_signature:
                return
            self._last_repetition_signature = signature
            warning = "The same action was produced multiple times, please change the action."
            logger.warning(warning + f" Action: {signature}")
            self.history_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": warning
                    }
                ]
            })
        else:
            self._last_repetition_signature = None
    
    def parse_action(self, output: str) -> Action:
        """ Parse action from text """
        if output is None or len(output) == 0:
            return None
            
        # Clean up the output
        output = output.strip()
        
        # Early detection of invalid responses
        if self._is_invalid_response(output):
            logger.debug(f"Detected invalid response: {output[:100]}...")
            return None
        
        # Extract action section using multiple strategies
        action_string = self._extract_action_string(output)
        
        # Validate extracted action string
        if not action_string or self._is_invalid_action_string(action_string):
            logger.debug(f"Invalid action string: {action_string}")
            return None
        
        # Try to parse with each action class
        output_action = self._try_parse_with_all_classes(action_string)
        
        # If still failed, try with fixes and fallbacks
        if output_action is None:
            output_action = self._try_parse_with_fixes(action_string)
        
        return output_action
    
    def _is_invalid_response(self, output: str) -> bool:
        """Check if response is clearly invalid"""
        # Check for common invalid patterns
        invalid_patterns = [
            r'^```\s*$',  # Just code blocks without content
            r'^```$',     # Just three backticks
            r'^\s*$',     # Empty or whitespace only
            r'^(Thought|Response):\s*$',  # Section headers without content
        ]
        
        for pattern in invalid_patterns:
            if re.match(pattern, output.strip(), re.DOTALL):
                return True
        
        # Check if output is too short to be meaningful
        if len(output.strip()) < 5:
            return True
            
        return False
    
    def _is_invalid_action_string(self, action_string: str) -> bool:
        """Check if extracted action string is invalid"""
        if not action_string or len(action_string.strip()) < 3:
            return True
            
        # Check for common invalid patterns in action strings
        invalid_action_patterns = [
            r'^```\s*$',     # Just code blocks
            r'^```[^`]*```$', # Code block without action
            r'^\s*$',        # Empty
        ]
        
        for pattern in invalid_action_patterns:
            if re.match(pattern, action_string.strip(), re.DOTALL):
                return True
                
        return False
    
    def _extract_action_string(self, output: str) -> str:
        """Extract action string using multiple patterns"""
        
        # Pattern 1: Action: ... (until next section or end) - 修复不应该在```处停止
        action_patterns = [
            r'Action:\s*(.*?)(?=\n\s*(?:Observation|Thought|Step \d+|$))',
            r'Action:\s*(.*?)$',
        ]
        
        for pattern in action_patterns:
            match = re.search(pattern, output, flags=re.DOTALL | re.IGNORECASE)
            if match:
                action_string = match.group(1).strip()
                # 清理可能的代码块标记 - 更全面的清理
                action_string = re.sub(r'^```[\w]*\n?', '', action_string)  # 移除开头的```
                action_string = re.sub(r'```\s*\)?$', '', action_string)    # 移除结尾的```和可能的)
                action_string = action_string.strip()
                if action_string and not self._is_invalid_action_string(action_string):
                    return action_string
        
        # Pattern 2: Look for action class names directly with better parsing
        action_names = ['CreateFile', 'EditFile', 'Bash', 'LOCAL_DB_SQL', 'BIGQUERY_EXEC_SQL', 'SNOWFLAKE_EXEC_SQL', 'Terminate']
        for action_name in action_names:
            # More comprehensive pattern that handles various formats
            patterns = [
                rf'{action_name}\s*\([^)]*\)(?:\s*:?\s*```.*?```)?',  # With code block (non-greedy)
                rf'{action_name}\s*\([^)]*\)',  # Simple function call
                rf'{action_name}\s*\([^)]*$',   # Incomplete function call
            ]
            
            for pattern in patterns:
                match = re.search(pattern, output, flags=re.DOTALL | re.IGNORECASE)
                if match:
                    action_candidate = match.group(0).strip()
                    # Fix incomplete calls
                    if action_candidate.count('(') > action_candidate.count(')'):
                        action_candidate += ')'
                    return action_candidate
        
        # Pattern 3: Look for standalone action names (sometimes the LLM just outputs the function name)
        for action_name in action_names:
            if action_name.lower() in output.lower():
                # Try to extract the full action around the action name
                pattern = rf'.*?{action_name}.*?(?=\n|$)'
                match = re.search(pattern, output, flags=re.DOTALL | re.IGNORECASE)
                if match:
                    candidate = match.group(0).strip()
                    if '(' in candidate:  # Ensure it looks like a function call
                        return candidate
        
        # Pattern 4: Return everything after "Action:" if found
        action_match = re.search(r'Action:?\s*(.*)', output, flags=re.DOTALL | re.IGNORECASE)
        if action_match:
            candidate = action_match.group(1).strip()
            if candidate and not self._is_invalid_action_string(candidate):
                return candidate
        
        # Last resort: if output contains any action name, try to parse the whole thing
        for action_name in action_names:
            if action_name.lower() in output.lower():
                return output.strip()
        
        # Fallback: return empty string instead of the entire output to avoid parsing noise
        return ""
    
    def _try_parse_with_all_classes(self, action_string: str) -> Action:
        """Try parsing with all available action classes"""
        for action_cls in self._AVAILABLE_ACTION_CLASSES:
            try:
                action = action_cls.parse_action_from_text(action_string)
                if action is not None:
                    return action
            except Exception as e:
                logger.debug(f"Failed to parse with {action_cls.__name__}: {e}")
                continue
        return None
    
    def _try_parse_with_fixes(self, action_string: str) -> Action:
        """Try parsing with common fixes applied"""
        fixes = [
            # Fix common formatting issues
            lambda s: s.replace(r"\_", "_").replace("'''", "```").strip(),
            # Remove common prefixes that might confuse parsing
            lambda s: re.sub(r'^(Response:|Thought:)\s*', '', s, flags=re.IGNORECASE).strip(),
            # Fix missing colon in CreateFile
            lambda s: re.sub(r'CreateFile\(filepath=([^)]+)\)\s*\n', r'CreateFile(filepath=\1):\n', s),
            # Fix malformed CreateFile syntax from error logs
            lambda s: re.sub(r"CreateFile\(filepath='([^']+)':\s*'''", r"CreateFile(filepath='\1'):\n```\n", s),
            lambda s: re.sub(r"CreateFile\(filepath='([^']+)':\s*```", r"CreateFile(filepath='\1'):\n```\n", s),
            # Fix incomplete action calls (add missing closing parenthesis)
            lambda s: s.rstrip(',') + ')' if s.count('(') > s.count(')') else s,
            # Fix incomplete Bash commands by adding closing quote and parenthesis
            lambda s: s + '")' if s.startswith('Bash(code="') and not s.endswith('")') else s,
            lambda s: s + "'))" if s.startswith('Bash(code="') and s.count('"') == 1 else s,
            # Normalize quotes
            lambda s: s.replace('"', '"').replace('"', '"').replace(''', "'").replace(''', "'"),
            # 修复CreateFile中的转义字符问题
            lambda s: self._fix_createfile_content(s),
            # Remove code block markers if they wrap the entire action
            lambda s: re.sub(r'^```(?:\w+)?\s*(.*?)\s*```$', r'\1', s, flags=re.DOTALL).strip(),
            # Fix common action name typos/variations
            lambda s: s.replace('Bash(', 'Bash(code=') if s.startswith('Bash(') and 'code=' not in s else s,
            # Remove trailing commas and fix syntax
            lambda s: re.sub(r',\s*\)', ')', s),
            # Try to extract just the action if there's extra text
            lambda s: self._extract_core_action(s),
        ]
        
        for fix_func in fixes:
            try:
                fixed_string = fix_func(action_string)
                if fixed_string and fixed_string != action_string:
                    logger.debug(f"Applied fix: {action_string[:50]}... -> {fixed_string[:50]}...")
                    action = self._try_parse_with_all_classes(fixed_string)
                    if action is not None:
                        return action
            except Exception as e:
                logger.debug(f"Fix function failed: {e}")
                continue
                
        return None
    
    def _extract_core_action(self, text: str) -> str:
        """Extract core action from potentially noisy text"""
        action_names = ['CreateFile', 'EditFile', 'Bash', 'LOCAL_DB_SQL', 'BIGQUERY_EXEC_SQL', 'SNOWFLAKE_EXEC_SQL', 'Terminate']
        
        for action_name in action_names:
            # Look for action name followed by parentheses
            pattern = rf'({action_name}\s*\([^)]*\)(?:\s*:.*?(?:```.*?```)?)?)'
            match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return text
    
    def _fix_createfile_content(self, action_string: str) -> str:
        """修复CreateFile中content参数的引号和转义字符问题"""
        if not action_string.startswith('CreateFile('):
            return action_string
            
        # 处理content参数中的转义字符问题
        # 查找content参数的开始和结束位置
        content_match = re.search(r'content="([^"]*(?:\\.[^"]*)*)"', action_string)
        if content_match:
            content_value = content_match.group(1)
            # 将\\n转换为真正的换行符
            fixed_content = content_value.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")
            # 重新构建action字符串
            fixed_action = action_string.replace(content_match.group(0), f'content="""{fixed_content}"""')
            return fixed_action
            
        return action_string

    
    def run(self):
        assert self.env is not None, "Environment is not set."
        result = ""
        done = False
        step_idx = 0
        obs = "You are in the folder now."
        retry_count = 0
        while not done and step_idx < self.max_steps:

            _, action = self.predict(
                obs
            )
            if action is None:
                logger.info("Failed to parse action from response, try again.")

                retry_count += 1
                if retry_count > 40:
                    logger.info("Failed to parse action from response, stop.")
                    break
                
                # Provide more specific feedback based on the response content
                response_preview = self.responses[-1][:200] if self.responses else "No response"
                if re.match(r'^```\s*$', response_preview.strip()):
                    obs = "Your response contains only code block markers (```). Please provide a valid action like: Bash(code=\"your command\") or CreateFile(filepath=\"path\")."
                elif 'Action:' not in response_preview:
                    obs = "Your response is missing an 'Action:' section. Please format your response as: Thought: [your reasoning] Action: [valid action]"
                elif len(response_preview.strip()) < 10:
                    obs = "Your response is too short. Please provide a complete thought and action."
                else:
                    obs = f"Failed to parse action from your response. Please provide a valid action like: Bash(code=\"command\"), CreateFile(filepath=\"path\"), EditFile(filepath=\"path\"), LOCAL_DB_SQL(sql_query=\"query\"), or Terminate(output=\"result\"). Your response was: {response_preview}..."
            else:
                logger.info("Step %d: %s", step_idx + 1, action)
                obs, done = self.env.step(action)
                step_idx += 1  # 只有成功执行action后才递增step

            if done:
                if isinstance(action, Terminate):
                    result = action.output
                logger.info("The task is done.")
                break

        return done, result

    def get_trajectory(self):
        trajectory = []
        for i in range(len(self.observations)):
            trajectory.append({
                "observation": self.observations[i],
                "thought": self.thoughts[i],
                "action": str(self.actions[i]),
                # "code": self.codes[i],
                "response": self.responses[i]
            })
        trajectory_log = {
            "Task": self.instruction,
            "system_message": self.system_message,
            "trajectory": trajectory
        }
        return trajectory_log


if __name__ == "__main__":
    agent = PromptAgent()
    response = """
BIGQUERY_EXEC_SQL(sql_query=\"\"\"
WITH purchase_users AS (
  SELECT DISTINCT user_pseudo_id
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE event_name = 'purchase' AND _TABLE_SUFFIX BETWEEN '20201201' AND '20201231'
),
pageviews AS (
  SELECT user_pseudo_id, COUNT(*) AS pageviews
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE event_name = 'page_view' AND _TABLE_SUFFIX BETWEEN '20201201' AND '20201231'
  GROUP BY user_pseudo_id
),
pageviews_by_user AS (
  SELECT 
    p.user_pseudo_id, 
    p.pageviews,
    CASE WHEN pu.user_pseudo_id IS NOT NULL THEN 'purchaser' ELSE 'non-purchaser' END AS user_type
  FROM pageviews p
  LEFT JOIN purchase_users pu ON p.user_pseudo_id = pu.user_pseudo_id
)
SELECT user_type, AVG(pageviews) AS avg_pageviews
FROM pageviews_by_user
GROUP BY user_type
\"\"\", is_save=True, save_path="avg_pageviews_dec_2020.csv")
"""

    response = """
BIGQUERY_EXEC_SQL(sql_query=\"\"\"
SELECT DISTINCT user_pseudo_id
FROM bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*
WHERE event_name = 'purchase' AND _TABLE_SUFFIX BETWEEN '20201201' AND '20201231'
\"\"\", is_save=False)
"""


    action = agent.parse_action(response)
    print(action)
