RUBRIC_PROMPT_ZH = """

# 任务说明
你是一个数据分析专家，你将基于给定的用户问题和助手回复对数据分析过程和结论进行评估。
你的任务是查看一段针对数据分析的回复和评分标准，然后根据该评分标准，对助手的回复，判断其符合标准的程度。

评估标准中会给出总分和解决问题所需满足的不同需求。其中：
- 总分：表示各项评分标准加和后的最高得分；
- 需求：表示助手需要满足的不同需求，每个需求会有多个评分标准。评分标准分为两类：
    - 一是确定性的标准，这类标准无需考虑不同路径，可直接评分；
    - 二是不确定性的标准，这类标准通常会有不同的路径实现，评估时请先基于助手的回复判断最佳匹配的路径，然后基于最佳匹配路径下的子标准进行评分。如若没有最佳匹配路径，则基于自身知识审视助手的回复是否正确符合需求目标，并计算是否合理，如果正确则得分，但该需求得分不能高于其他路径得分。

标准类型取值范围为：完备性，精确性，结论性

最终算分逻辑：
最终得分=各需求得分之和。
分需求得分=各评分标准得分
各评分标准得分=直接评分 或 最佳匹配路径得分 或 未匹配路径得分
最匹配路径得分=该路径下的子标准的得分之和

请严格按照评分标准逐条检查助手是否覆盖并回答了所有需求。如果在回答末尾看到“[Answer image attachments...]”提示，则说明附带了图像附件，请结合这些图片中的信息一起评估（图像与文字同等重要）。

【用户问题开始】
{user_query}
【用户问题结束】

【助手分析历史开始】
{assistant_response}
【助手分析历史结束】

【评分标准项开始】
{rubric}
【评分标准项结束】

你需要根据评分标注逐条进行分析并打分。
# 回复格式如下：
```json
{{
    "需求1": {{
        "标准1.1": {{
            "分析": "详细描述助手的相关分析，判断是否满足标准1.1，并赋分",
            "标准类型": "",
            "得分": int,
        }},
        "标准1.2": {{
            "分析": "分析最匹配路径的原因，确定最匹配路径：最佳匹配路径为路径1.2.x",
            "最佳匹配路径分析": {{
                "标准1.2.x.1": {{
                    "分析": "详细描述助手的相关分析，判断是否满足标准1.2.x.1，并赋分",
                    "标准类型": "",
                    "得分": int,
                }},
                "标准1.2.x.2": {{
                    "分析": "详细描述助手的相关分析，判断是否满足标准1.2.x.2，并赋分",
                    "标准类型": "",
                    "得分": int,
                }},
            }}
            "得分": int,
        }},
        "总得分": int, 
    }},
    "需求2" : {{
        "标准2.1": {{
            "分析": "分析最匹配路径的原因，确定最匹配路径：无最佳匹配路径。根据自身知识判断是否符合标准2.1。参考其他路径，应该满足标准2.1.notfound.1：xxx； 标准2.1.notfound.2：xxx",
            "最佳匹配路径分析": {{
                "标准2.1.notfound.1": {{
                    "分析": "",
                    "标准类型": "",
                    "得分": int,
                }},
                "标准2.1.notfound.2": {{
                    "分析": "",
                    "标准类型": "",
                    "得分": int,
                }},
            }}
            "得分": int,
        }},
    }},
    "总得分": int, 
}}
```
"""

RUBRIC_PROMPT_EN = """

# Task Instruction
You are a senior data-analytics evaluator. Given a user question, the assistant's analysis history, and a rubric, evaluate how well the assistant addressed each requirement.

The rubric provides:
- A total possible score.
- Multiple requirements, each containing one or more scoring criteria.
  - Deterministic criteria have fixed expectations and can be scored directly.
  - Path-dependent criteria describe several alternative solution paths. First identify the best-matching path according to the assistant's response, then score the sub-criteria under that path. If no path fits, reason independently based on your own domain knowledge; such fallback scores cannot exceed the highest path score.

Criterion types fall into completeness, accuracy, or conclusion quality.

Scoring logic:
- Final score = sum of requirement scores.
- Requirement score = sum of its criteria scores.
- Criterion score = direct score, best-path score, or fallback score.
- Best-path score = sum of the matched path's sub-criteria scores.

Review every requirement sequentially; missing coverage should reduce the score accordingly. If the prompt mentions “[Answer image attachments...]”, treat the referenced images as part of the assistant’s evidence and evaluate them alongside the text.

【User Question】
{user_query}
【End User Question】

【Assistant Analysis History】
{assistant_response}
【End Assistant Analysis】

【Rubric】
{rubric}
【End Rubric】

Follow the rubric meticulously and provide a detailed breakdown. Return strictly in the JSON format below:
```json
{{
    "Requirement 1": {{
        "Criterion 1.1": {{
            "analysis": "Explain how the assistant handled this criterion and assign a score.",
            "criterion_type": "",
            "score": int
        }},
        "Criterion 1.2": {{
            "analysis": "Explain why a specific path is the best match and analyze its sub-criteria.",
            "best_path_analysis": {{
                "Criterion 1.2.x.1": {{
                    "analysis": "Explain performance on sub-criterion 1.2.x.1 and score it.",
                    "criterion_type": "",
                    "score": int
                }},
                "Criterion 1.2.x.2": {{
                    "analysis": "",
                    "criterion_type": "",
                    "score": int
                }}
            }},
            "score": int
        }},
        "total_score": int
    }},
    "Requirement 2": {{
        "Criterion 2.1": {{
            "analysis": "If no path matches, explain why and reason independently (e.g., refer to Criterion 2.1.notfound.1).",
            "best_path_analysis": {{
                "Criterion 2.1.notfound.1": {{
                    "analysis": "",
                    "criterion_type": "",
                    "score": int
                }},
                "Criterion 2.1.notfound.2": {{
                    "analysis": "",
                    "criterion_type": "",
                    "score": int
                }}
            }},
            "score": int
        }},
        "total_score": int
    }},
    "total_score": int
}}
```
"""

GSB_PROMPT_TEXT_ZH = """
你是一个数据分析评估专家，需要比较以下两份报告的好坏。
请只从以下两个维度进行详细评估：
1. 报告可读性强，易懂易读。
2. 分析专业、有深度。

为每个维度进行评分，每个维度的评分范围为 -10 ~ 10。
注意：
+ 所有分析和评分均是对比分析，对比的是待评分报告和基准报告。
+ -10 表示待评分报告在该维度表现远远差于基准报告；
+ 0 表示待评分报告在该维度表现与基准报告大致相同；
+ +10 表示待评分报告在该维度表现远远好于基准报告；
+ 总维度的评分范围为 -10 ~ 10，为各子维度得分加和。
+ 如果两份报告在某个维度上都很弱或都很强，应在分析中说明，并尽量将该维度得分保持在接近 0 的区间，而不要轻易给出极端高分或极端低分。
+ 同一个问题尽量在最相关的子维度中体现，不要在多个子维度中重复计分。

其中：
报告可读性具体表现为以下几个子维度（聚焦文字表述本身，不考虑图像呈现）：
- 用简洁的方式传递复杂信息，让读者快速抓住重点。报告格式美观，对重点信息进行加粗/斜体等标记。该子维度的评分范围为 -4 ~ 4。
- 逻辑结构清晰、段落层次分明（如使用小标题、列表等），让读者顺畅跟随分析节奏。该子维度的评分范围为 -3 ~ 3。
- 叙述中善于总结关键结论或行动项，能够在句末/段末点明要点。该子维度的评分范围为 -2 ~ 2。
- 语言简练，避免冗长与重复表达，不因为“写得更长”就给高分；堆砌术语但不增加理解反而应扣分。该子维度的评分范围为 -1 ~ 1。

分析专业有深度具体表现为以下几个子维度：
- 多维度多角度进行分析，考虑不同维度、不同场景下的影响。该子维度的评分范围为 -4 ~ 4。
- 分析角度专业，结论明确，归因有理有据，论据充分详实。该子维度的评分范围为 -3 ~ 3。
- 分析结果贴合实际，与报告中给出的数据和业务场景保持一致，没有凭空假设或编造数字；结论有价值，能够为决策提供依据。该子维度的评分范围为 -2 ~ 2。
- 能够预估建议的潜在影响，并明确说明影响方向和大致逻辑，而不是空泛表述。该子维度的评分范围为 -1 ~ 1。

输出格式如下：
```json
{{
    "可读性" : {{
        "分析" : "在子维度xxx上，基准报告的优劣xxx，待评分报告的优劣xxx，对比两者的差异分析，待评估报告在该子维度得分xx。",
        "分析总结" : "待评估报告的可读性分析总结",
        "得分": int, 
    }},
    "分析专业深度" : {{
        "分析" : "在子维度xxx上，基准报告的优劣xxx，待评分报告的优劣xxx，对比两者的差异分析，待评估报告在该子维度得分xx。",
        "分析总结" : "待评估报告的分析专业深度分析总结",
        "得分" : int,
    }},
}}
```
【待评估报告开始】
{content1}
【待评估报告结束】

【基准报告开始】
{content2}
【基准报告结束】
"""



GSB_PROMPT_TEXT_EN = """
You are an expert reviewer of data-analysis reports. Compare the following candidate report with the baseline report.
Evaluate two aspects in detail:
1. Readability and clarity.
2. Analytical professionalism and depth.

For each aspect, assign a score in the range -10 to 10.
Guidelines:
- All analysis is comparative: judge the candidate relative to the baseline.
- -10: the candidate is dramatically worse on this aspect.
- 0: the candidate matches the baseline on this aspect.
- +10: the candidate is dramatically better on this aspect.
- The total score equals the sum of sub-dimension scores (sub-dimension ranges add up to -10~10).
- If both reports are uniformly weak or uniformly strong on a given aspect, explain this and keep the score near 0 instead of using extreme positive or negative values.
- Do not double-count the same issue in multiple sub-dimensions; reflect each issue mainly in the most relevant sub-dimension.

Readability (text-only) can be judged via:
- Conveying complex information concisely (e.g., clean and elegant format, bold/italic highlights) — score range -4~4.
- Logical flow and paragraph organization (headings, lists, progressive storytelling) — score range -3~3.
- Emphasizing key takeaways or action items in the narrative — score range -2~2.
- Concise wording without redundancy; do not reward verbosity. Longer text that does not improve clarity or understanding should not increase the score — score range -1~1.

Analytical professionalism can be judged via:
- Multi-angle analysis that considers different segments/scenarios — score range -4~4.
- Professional reasoning with clear conclusions and sufficient evidence — score range -3~3.
- Practical and grounded insights that are consistent with the provided data and business context, and that support decisions; avoid fabricated numbers or unjustified claims — score range -2~2.
- Anticipation of potential impact, with a clear explanation of likely direction and rationale rather than vague statements — score range -1~1.

Output JSON format:
```json
{{
    "Readability": {{
        "analysis": "Discuss each sub-dimension, compare both reports, and justify the score.",
        "summary": "Overall readability assessment.",
        "score": int
    }},
    "Analytical Depth": {{
        "analysis": "Discuss sub-dimensions, compare both reports, and justify the score.",
        "summary": "Overall analytical depth assessment.",
        "score": int
    }}
}}
```
【Candidate Report】
{content1}
【End Candidate Report】

【Baseline Report】
{content2}
【End Baseline Report】
"""


GSB_PROMPT_VIS_ZH = """
你是一个资深的数据可视化与分析报告评估专家，需要**只针对“洞察呈现与可视化”这一维度**比较以下两份报告，其它维度（如业务结论是否正确、推理是否严谨等）不必考虑。

请从“可视化是否专业且好看”的角度，围绕以下三个子维度逐条分析并打分，最终得分为三者之和（范围 -10 ~ +10）：
1. 图表清晰度与美观性（-4 ~ +4）：图表整体观感是否专业、简洁、好看且易读。重点关注：标题、坐标轴、图例、标签是否完整清晰；字号、线条粗细、标记大小是否合适；色彩搭配是否和谐、有足够对比度但不过度花哨；布局是否对齐、留白是否合理；是否避免过多装饰元素和视觉噪音。
2. 图表恰当性与准确性（-3 ~ +3）：图表类型与编码方式是否适合要表达的数据和问题（如趋势/变化、对比、占比、分布、相关性等）；轴刻度、排序、分组是否合理；是否存在会误导读者的设计（如不从零开始的坐标、夸张的 3D 效果、双轴滥用等）；图中数据标注是否准确，是否与文字结论一致。
3. 图文协同与洞察力（-3 ~ +3）：文字是否主动引用和解释图表（例如“从图 2 中蓝色柱子可以看到……”），是否点出关键趋势、异常、分组差异，而不是仅重复数字；图表是否帮助读者更快抓住核心结论、支撑文字洞察，而不是与正文脱节或仅作装饰。

整体得分解释（针对“洞察呈现与可视化”这一维度）：  
- -10：候选报告在可视化的专业性、美观性、准确性等方面都显著劣于基准报告，几乎所有关键点都做得更差。  
- 0：候选报告在可视化上的整体表现与基准报告大体相当，没有明显优劣。  
- +10：候选报告在可视化的专业度、美观性、设计准确性、图文协同和洞察突出方面都远好于基准报告，整体体验明显更佳。

所有分值均为候选报告相对于基准报告的表现差异：负分表示明显更差，0 表示相当，正分表示更好。若候选报告或基准报告附带图像，请结合图片信息判断。如果两份报告在可视化方面都很弱（几乎没有图表或仅有非常粗糙的可视化），请在分析中说明，并倾向给接近 0 分，而不要随意给出极端高分或低分。

输出 JSON（只保留一个总维度“洞察呈现与可视化”）：
```json
{{
    "洞察呈现与可视化": {{
        "分析": "针对三个子维度的对比分析与理由。",
        "得分": int
    }}
}}
```
【待评估报告开始】
{content1}
【待评估报告结束】

【基准报告开始】
{content2}
【基准报告结束】
"""


GSB_PROMPT_VIS_EN = """
You are a senior data visualization and analytics report reviewer. You must compare the candidate report against the baseline **only on the \"Insight Presentation & Visualization\" dimension**. Ignore all other aspects such as reasoning correctness, business impact, or modeling choices.

Evaluate whether the visualizations are professional and visually appealing, using the following three sub-dimensions (final score = sum of them, range -10 ~ +10):
1. Visual clarity & professionalism (-4 ~ +4): Judge whether the visuals look professional, clean, and aesthetically pleasing while remaining easy to read. Consider whether titles, axes, legends, and labels are complete and clear; font sizes and line weights are appropriate; color choices and contrast are harmonious and not overly flashy; layout, alignment, and spacing are well organized; and unnecessary decorations or chartjunk are avoided.
2. Chart appropriateness & accuracy (-3 ~ +3): Check whether chart types and encodings match the data and analytical task (trend, comparison, composition, distribution, correlation, etc.); axis scales, sorting, and grouping are sensible; there is no misleading design (e.g., truncated axes, exaggerated 3D effects, or arbitrary dual axes); and plotted values and proportions are accurate and consistent with the written conclusions.
3. Text–visual synergy & insightfulness (-3 ~ +3): Assess whether the narrative explicitly references and explains the charts (e.g., \"as shown by the blue bar in Figure 2\"), highlights key trends, outliers, and segment differences rather than merely restating numbers, and whether the visuals help readers quickly grasp and trust the main insights instead of being decorative or disconnected from the text.

All scores are relative (candidate vs baseline). Negative = clearly worse, zero = comparable, positive = better. When either report contains images, you must use both the visuals and the surrounding text to form your judgment. If both reports have very weak visualization (almost no charts or only very rough visuals), state this in your analysis and keep scores near 0 instead of assigning extreme values.

Return JSON with a single top-level dimension:
```json
{{
    "Insight Presentation & Visualization": {{
        "analysis": "Discuss each sub-dimension, compare both reports, explain the score.",
        "score": int
    }}
}}
```
【Candidate Report】
{content1}
【End Candidate Report】

【Baseline Report】
{content2}
【End Baseline Report】
"""


def get_rubric_prompt(language: str) -> str:
    language = (language or "zh").lower()
    if language == "en":
        return RUBRIC_PROMPT_EN
    return RUBRIC_PROMPT_ZH


def get_gsb_prompt(language: str, channel: str = "text") -> str:
    language = (language or "zh").lower()
    channel = (channel or "text").lower()
    if channel == "visual":
        return GSB_PROMPT_VIS_EN if language == "en" else GSB_PROMPT_VIS_ZH
    return GSB_PROMPT_TEXT_EN if language == "en" else GSB_PROMPT_TEXT_ZH


RUBRIC_PROMPT = RUBRIC_PROMPT_ZH
GSB_PROMPT = GSB_PROMPT_TEXT_ZH
GSB_PROMPT_V5 = GSB_PROMPT_VIS_ZH
