from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

from openhands.llm.tool_names import TASK_TRACKER_TOOL_NAME

# _DETAILED_TASK_TRACKER_DESCRIPTION = """This tool provides structured task management capabilities for development workflows.
# It enables systematic tracking of work items, progress monitoring, and efficient
# organization of complex development activities.

# The tool maintains visibility into project status and helps communicate
# progress effectively to users.

# ## Application Guidelines

# Utilize this tool in the following situations:

# 1. Multi-phase development work - When projects involve multiple sequential or
#    parallel activities
# 2. Complex implementation tasks - Work requiring systematic planning and
#    coordination across multiple components
# 3. Explicit user request for task organization - When users specifically ask
#    for structured task management
# 4. Multiple concurrent requirements - When users present several work items
#    that need coordination
# 5. Project initiation - Capture and organize user requirements at project start
# 6. Work commencement - Update task status to in_progress before beginning
#    implementation. Maintain focus by limiting active work to one task
# 7. Task completion - Update status to done and identify any additional work
#    that emerged during implementation

# ## Situations Where Tool Usage Is Unnecessary

# Avoid using this tool when:

# 1. Single atomic tasks that require no decomposition
# 2. Trivial operations where tracking adds no organizational value
# 3. Simple activities completable in minimal steps
# 4. Pure information exchange or discussion

# Note: For single straightforward tasks, proceed with direct implementation
# rather than creating tracking overhead.

# ## Usage Scenarios

# **Scenario A: Feature Development with Validation**
# User request: "Build a user authentication system with login/logout functionality.
# Don't forget to include input validation and error handling!"

# Response approach: I'll implement a user authentication system with comprehensive
# validation. Let me organize this work systematically.

# *Task breakdown includes:*
# 1. Design authentication API endpoints and data models
# 2. Implement user login/logout controllers with session management
# 3. Add client-side form validation and error display
# 4. Create backend input sanitization and security checks
# 5. Implement comprehensive error handling for edge cases
# 6. Perform integration testing and fix any issues

# **Scenario B: Codebase Refactoring**
# User request: "I need to update all instances of the method 'fetchData' to
# 'retrieveInformation' throughout the entire project"

# Response approach: Let me first analyze your codebase to identify all locations
# where 'fetchData' appears.

# *After code analysis*

# I've located 12 occurrences of 'fetchData' across 6 files in your project.
# I'll create a systematic plan to update these references.

# *Organized task list includes specific file-by-file updates*

# **Scenario C: Multi-feature Development**
# User request: "Set up a blog platform with these components: admin dashboard,
# article management, comment system, and user profiles."

# Response approach: I'll help build your blog platform. Let me break down these
# components into manageable implementation phases.

# *Creates structured plan with each feature decomposed into specific development tasks*

# ## Counter-examples - Direct Implementation Preferred

# **Counter-example A: Simple inquiry**
# User request: "What's the syntax for a for loop in JavaScript?"

# Response approach: Here's how to write a for loop in JavaScript:

# ```javascript
# for (let i = 0; i < array.length; i++) {
#     console.log(array[i]);
# }
# ```

# *No task tracking needed - single informational response*

# **Counter-example B: Minor modification**
# User request: "Please add a docstring to the processPayment function explaining
# its parameters."

# Response approach: I'll add a docstring to explain the processPayment function.

# *Direct edit without task tracking for simple modification*

# ## Status Management and Workflow

# 1. **Status Values**: Track work using these states:
#    - todo: Not yet initiated
#    - in_progress: Currently active (maintain single focus)
#    - done: Successfully completed

# 2. **Workflow Practices**:
#    - Update status dynamically as work progresses
#    - Mark completion immediately upon task finish
#    - Limit active work to ONE task at any given time
#    - Complete current activities before initiating new ones
#    - Remove obsolete tasks from tracking entirely

# 3. **Completion Criteria**:
#    - Mark tasks as done only when fully achieved
#    - Keep status as in_progress if errors, blocks, or partial completion exist
#    - Create new tasks for discovered issues or dependencies
#    - Never mark done when:
#        - Test suites are failing
#        - Implementation remains incomplete
#        - Unresolved errors persist
#        - Required resources are unavailable

# 4. **Task Organization**:
#    - Write precise, actionable descriptions
#    - Decompose complex work into manageable units
#    - Use descriptive, clear naming conventions

# When uncertain, favor using this tool. Proactive task management demonstrates
# systematic approach and ensures comprehensive requirement fulfillment.
# """

# _SHORT_TASK_TRACKER_DESCRIPTION = """Provides structured task management for development workflows, enabling progress
# tracking and systematic organization of complex coding activities.

# * Apply to multi-phase projects (3+ distinct steps) or when managing multiple user requirements
# * Update status (todo/in_progress/done) dynamically throughout work
# * Maintain single active task focus at any time
# * Mark completion immediately upon task finish
# * Decompose complex work into manageable, actionable units
# """


_DETAILED_TASK_TRACKER_DESCRIPTION = """此工具为开发工作流程提供结构化的任务管理功能。
它能够系统地跟踪工作项、监控进度并高效地组织复杂的开发活动。

该工具能够保持项目状态的可见性，并帮助有效地向用户传达进度。

## 应用指南

请在以下情况下使用此工具：

1. 多阶段开发工作 - 项目涉及多个连续或并行活动

2. 复杂的实施任务 - 需要跨多个组件进行系统规划和协调的工作

3. 用户明确要求进行任务组织 - 用户明确要求进行结构化任务管理

4. 多个并发需求 - 用户提出多个需要协调的工作项

5. 项目启动 - 在项目启动时捕获并组织用户需求

6. 工作开始 - 在开始实施之前将任务状态更新为“in_progress”。通过将当前工作限制为一项任务来保持专注
7. 任务完成 - 将状态更新为“已完成”，并识别实施过程中出现的任何额外工作

## 无需使用工具的情况

以下情况请避免使用此工具：

1. 无需分解的单个原子任务
2. 跟踪不会增加组织价值的琐碎操作
3. 只需最少步骤即可完成的简单活动
4. 纯粹的信息交换或讨论

注意：对于单个简单的任务，请直接实施，而不是增加跟踪开销。

## 使用场景

**场景 A：包含验证的功能开发**
用户请求：“构建一个具有登录/注销功能的用户身份验证系统。
不要忘记包含输入验证和错误处理！”

回复方式：我将实现一个具有全面验证功能的用户身份验证系统。让我系统地组织这项工作。

*任务细分包括：*
1. 设计身份验证 API 端点和数据模型
2. 实现带有会话管理的用户登录/注销控制器
3. 添加客户端表单验证和错误显示
4. 创建后端输入清理和安全检查
5. 针对边缘情况实现全面的错误处理
6. 执行集成测试并修复所有问题

**场景 B：代码库重构**
用户请求：“我需要将整个项目中所有‘fetchData’方法的实例更新为‘retrieveInformation’。”

响应方式：首先让我分析您的代码库，找出所有出现‘fetchData’的位置。

*代码分析后*

我已在您的项目中的 6 个文件中找到了 12 个‘fetchData’。
我将制定一个系统性的计划来更新这些引用。

*已整理好的任务列表，其中包含每个文件的具体更新*

**场景 C：多功能开发**
用户请求：“搭建一个包含以下组件的博客平台：管理面板、
文章管理、评论系统和用户资料。”

响应方式：我将帮助您构建博客平台。我将把这些组件分解成易于管理的实施阶段。

*创建结构化计划，将每个功能分解为具体的开发任务*

## 反例 - 直接实施优先

**反例 A：简单询问**
用户请求：“JavaScript 中 for 循环的语法是什么？”

响应方式：以下是如何在 JavaScript 中编写 for 循环：

```javascript
for (let i = 0; i < array.length; i++) {
console.log(array[i]);
}
```

*无需任务跟踪 - 单一信息响应*

**反例 B：少量修改**
用户请求：“请为 processPayment 函数添加一个文档字符串，解释其参数。”

响应方式：我将添加一个文档字符串来解释 processPayment 函数。

*无需任务跟踪即可直接编辑，方便进行简单修改*

## 状态管理和工作流程

1. **状态值**：使用以下状态跟踪工作：
- todo：尚未启动
- in_progress：当前处于活动状态（保持单一焦点）
- done：已成功完成

2. **工作流程实践**：
- 随着工作进展动态更新状态
- 任务完成后立即标记完成
- 在任何给定时间将活动工作限制为一项任务
- 在启动新活动之前完成当前活动
- 将过时的任务从跟踪中完全移除

3. **完成标准**：
- 仅在完全完成时将任务标记为完成
- 如果存在错误、阻碍或部分完成，则保持状态为 in_progress
- 为发现的问题或依赖项创建新任务
- 在以下情况下切勿标记为完成：
- 测试套件失败
- 实施仍未完成
- 未解决的错误仍然存​​在
- 所需资源不可用

4. **任务组织**：
- 编写精确、可操作的描述
- 将复杂工作分解为可管理单元
- 使用描述性、清晰的命名规范

如有疑问，建议使用此工具。主动式任务管理体现了系统化的方法，并确保全面满足需求。
"""

_SHORT_TASK_TRACKER_DESCRIPTION = """为开发工作流提供结构化的任务管理，支持进度跟踪和复杂编码活动的系统化组织。

* 适用于多阶段项目（3 个以上不同步骤）或管理多个用户需求
* 在整个工作过程中动态更新状态（待办事项/进行中/完成）
* 随时保持单个活动任务的焦点
* 任务完成后立即标记完成
* 将复杂工作分解为可管理、可操作的单元
"""

def create_task_tracker_tool(
    use_short_description: bool = False,
) -> ChatCompletionToolParam:
    description = (
        _SHORT_TASK_TRACKER_DESCRIPTION
        if use_short_description
        else _DETAILED_TASK_TRACKER_DESCRIPTION
    )
    return ChatCompletionToolParam(
        type='function',
        function=ChatCompletionToolParamFunctionChunk(
            name=TASK_TRACKER_TOOL_NAME,
            description=description,
            parameters={
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'enum': ['view', 'plan'],
                        # 'description': 'The command to execute. `view` shows the current task list. `plan` creates or updates the task list based on provided requirements and progress. Always `view` the current list before making changes.',
                        'description': '要执行的命令。“view”显示当前任务列表。“plan”根据提供的需求和进度创建或更新任务列表。进行更改前，请务必“view”当前列表。',
                    },
                    'task_list': {
                        'type': 'array',
                        # 'description': 'The full task list. Required parameter of `plan` command.',
                        'description': '完整的任务列表。`plan` 命令的必需参数。',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {
                                    'type': 'string',
                                    # 'description': 'Unique task identifier',
                                    'description': '唯一任务标识符',
                                },
                                'title': {
                                    'type': 'string',
                                    # 'description': 'Brief task description',
                                    'description': '简要任务描述',
                                },
                                'status': {
                                    'type': 'string',
                                    # 'description': 'Current task status',
                                    'description': '当前任务状态',
                                    'enum': ['todo', 'in_progress', 'done'],
                                },
                                'notes': {
                                    'type': 'string',
                                    # 'description': 'Optional additional context or details',
                                    'description': '可选的附加上下文或细节',
                                },
                            },
                            'required': ['title', 'status', 'id'],
                            'additionalProperties': False,
                        },
                    },
                },
                'required': ['command'],
                'additionalProperties': False,
            },
        ),
    )
