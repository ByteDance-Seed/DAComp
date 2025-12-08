eval_prompt = """
# Task Description
You are a professional data architect. You will evaluate a model blueprint based on a given user question and a scoring rubric.
Your task is to review a set of scoring criteria for the model blueprint, and then, based on these criteria, assess the blueprint to determine the extent to which it meets the standards.

The scoring rubric provides a total score and various requirements. Where:
- Total Score: Represents the maximum possible score after summing all scoring criteria.
- Requirements: Represent different needs the assistant must satisfy. Each requirement contains multiple scoring criteria. These criteria are divided into two categories:
    - 1. Deterministic criteria: These can be scored directly without considering different implementation paths.
    - 2. Non-deterministic criteria: These usually have multiple implementation paths. When evaluating, first determine the "best matching path" based on the assistant's response, and then score based on the sub-criteria under that path. If there is no clearly matching path, use your own expertise to judge whether the assistant's response correctly meets the requirement's goal and calculate if it is reasonable. If correct, assign points, but the score for this requirement cannot exceed the maximum score of other defined paths.

Final Scoring Logic:
Final Score = Sum of all requirement scores.
Requirement Score = Sum of all criteria scores within that requirement.
Criteria Score = Direct score OR Best matching path score OR Unmatched path score OR Sum of sub-criteria.
Best Matching Path Score = Sum of the scores of the sub-criteria under that path.

Please analyze and score item by item according to the rubric. If you have any hesitation on any point, do not guess or make subjective assumptions—assign 0 points directly. **You must provide evidence; if evidence is missing, assign 0 points.**

[User Question Start]
{user_query}
[User Question End]

[Model Blueprint Start]
{model_blueprint}
[Model Blueprint End]

[Scoring Rubric Start]
{rubric}
[Scoring Rubric End]

You need to analyze and score each item one by one according to the scoring rubric.
# Response format as follows:
```json
{{
    "Requirement1": {{
        "Criterion1.1": {{
            "Analysis": "Carefully read the content of the model blueprint, determine whether it meets Criterion 1.1, and assign a score.",
            "Criterion1.1.x.1": {{
                "Analysis": "Carefully read the content of the model blueprint, determine whether it meets Criterion 1.1.x.1, and assign a score.",
                "Evidence": [],
                "Score": int
            }},
            "Criterion1.1.x.2": {{
                "Analysis": "Carefully read the content of the model blueprint, determine whether it meets Criterion 1.1.x.2, and assign a score.",
                "Evidence": [],
                "Score": int
            }},
            "Score": int
        }},
        "Criterion1.2": {{
            "Analysis": "Analyze the reason for the best matching path, determine the best matching path: The best matching path is Path 1.2.x",
            "Criterion1.2.x.1": {{
                "Analysis": "Carefully read the content of the model blueprint, determine whether it meets Criterion 1.2.x.1, and assign a score.",
                "Evidence": [],
                "Score": int
            }},
            "Criterion1.2.x.2": {{
                "Analysis": "Carefully read the content of the model blueprint, determine whether it meets Criterion 1.2.x.2, and assign a score.",
                "Evidence": [],
                "Score": int
            }},
            "Score": int
        }},
        "Total Score": int
    }},
    "Requirement2" : {{
        "Criterion2.1": {{
            "Analysis": "Analyze the reason for the best matching path, determine the best matching path: No best matching path found. Judge whether it meets Standard 2.1 based on your own knowledge. Referencing other paths, it should meet Criterion 2.1.notfound.1: xxx; Criterion 2.1.notfound.2: xxx",
            "Criterion2.1.x.1": {{
                "Analysis": "Carefully read the content of the model blueprint, determine whether it meets Criterion 2.1.x.1, and assign a score.",
                "Evidence": [],
                "Score": int
            }},
            "Criterion2.1.x.2": {{
                "Analysis": "Carefully read the content of the model blueprint, determine whether it meets Criterion 2.1.x.2, and assign a score.",
                "Evidence": [],
                "Score": int
            }},
            "Score": int
        }}
    }},
    "Total Score": int
}}

"""


eval_prompt_zh = """
# 任务说明
你是一个专业的数据架构师，你将基于给定的用户问题和评分标准对模型蓝图进行评估。
你的任务是查看一段针对模型蓝图评分标准，然后根据该评分标准，对模型蓝图评估，判断其符合标准的程度。

评估标准中会给出总分和不同需求。其中：
- 总分：表示各项评分标准加和后的最高得分；
- 需求：表示助手需要满足的不同需求，每个需求会有多个评分标准。评分标准分为两类：
    - 一是确定性的标准，这类标准无需考虑不同路径，可直接评分；
    - 二是不确定性的标准，这类标准通常会有不同的路径实现，评估时请先基于助手的回复判断最佳匹配的路径，然后基于最佳匹配路径下的子标准进行评分。如若没有最佳匹配路径，则基于自身知识审视助手的回复是否正确符合需求目标，并计算是否合理，如果正确则得分，但该需求得分不能高于其他路径得分。

最终算分逻辑：
最终得分=各需求得分之和。
分需求得分=各评分标准得分
各评分标准得分=直接评分 或 最佳匹配路径得分 或 未匹配路径得分 或 小标准之和
最匹配路径得分=该路径下的子标准的得分之和

请根据评分标准逐条分析并打分。只要你有任何迟疑的点，不要猜测，不要主观臆断，直接打0分。务必提供证据；未能提供证据即记 0 分。

【用户问题开始】
{user_query}
【用户问题结束】

【模型蓝图开始】
{model_blueprint}
【模型蓝图结束】

【评分标准项开始】
{rubric}
【评分标准项结束】

你需要根据评分标注逐条进行分析并打分。
# 回复格式如下：
```json
{{
    "需求1": {{
        "标准1.1": {{
            "分析": "详细阅读模型蓝图的内容,判断是否满足标准1.1, 并赋分",
            "标准1.1.x.1": {{
                "分析": "详细阅读模型蓝图的内容,判断是否满足标准1.1.x.1,并赋分",
                "证据": [],
                "得分": int
            }},
            "标准1.1.x.2": {{
                "分析": "详细阅读模型蓝图的内容,判断是否满足标准1.1.x.2, 并赋分",
                "证据": [],
                "得分": int
            }},
            "得分": int,
        }},
        "标准1.2": {{
            "分析": "分析最匹配路径的原因,确定最匹配路径: 最佳匹配路径为路径1.2.x",
            "标准1.2.x.1": {{
                "分析": "详细阅读模型蓝图的内容,判断是否满足标准1.2.x.1, 并赋分",
                "证据": [],
                "得分": int
            }},
            "标准1.2.x.2": {{
                "分析": "详细阅读模型蓝图的内容,判断是否满足标准1.2.x.2, 并赋分",
                "证据": [],
                "得分": int
            }},
            "得分": int,
        }},
        "总得分": int, 
    }},
    "需求2" : {{
        "标准2.1": {{
            "分析": "分析最匹配路径的原因,确定最匹配路径:无最佳匹配路径。根据自身知识判断是否符合标准2.1。参考其他路径,应该满足标准2.1.notfound.1:xxx； 标准2.1.notfound.2:xxx",
            "标准2.1.x.1": {{
                "分析": "详细阅读模型蓝图的内容,判断是否满足标准2.1.x.1,并赋分",
                "证据": [],
                "得分": int
            }},
            "标准2.1.x.2": {{
                "分析": "详细阅读模型蓝图的内容,判断是否满足标准2.1.x.2,并赋分",
                "证据": [],
                "得分": int
            }},
            "得分": int,
        }},
    }},
    "总得分": int, 
}}
```

"""

