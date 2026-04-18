# Python 辩论对战评测系统

这个项目用于评测学生编写的 Python Agent 是否能够围绕给定辩论材料进行多轮攻防，并由裁判模型给出胜负结果。

## 目录结构

```text
NLP@2026/
├── debate_eval/
│   ├── api.py
│   ├── cli.py
│   ├── engine.py
│   └── loader.py
├── materials/
├── students/
├── gen_materials.py
├── utils.py
└── README.md
```

## 系统功能

1. 从 `students/` 目录读取学生提交的 `*.py` 文件。
2. 检查每个学生文件是否定义了合法的 `Agent` 类，并验证其是否继承 `BaseAgent`。
3. 从 `materials/` 读取辩论材料。
4. 默认从材料库中随机抽取 1 篇材料进行评测，也可以指定某一篇材料。
5. 正反双方轮流发言，默认共 10 轮。
6. 每次学生发言都会实时打印到终端。
7. 辩论结束后调用裁判模型进行胜负判定。
8. 打印裁判原始输出、是否触发回退、最终胜负结果。
9. 统计学生侧 `chat()` 的调用次数、输入字符数、输出字符数。
10. 所有真实模型调用都统一经过 `utils.py`，便于后续统一替换模型、API 地址或认证方式。

## 统一 API 入口

项目中所有真实模型调用都集中在 `utils.py`。

当前配置：

- `student_model`: 学生发言使用的模型
- `judger_model`: 裁判判定使用的模型
- `material_model`: 材料生成使用的模型

当前统一调用函数：

- `chat(messages, model)`: 最底层统一调用入口，直接发起 chat completion 请求
- `chat_text(messages, model)`: 返回文本内容
- `student_chat(messages)`: 学生 Agent 调用的统一入口
- `judge_chat(messages)`: 裁判调用的统一入口
- `material_chat(messages)`: 材料生成调用的统一入口

这意味着：

1. 如果你以后要换模型名，只改 `utils.py` 即可。
2. 如果你以后要换 `base_url`、`api_key`、供应商兼容层，只改 `utils.py` 即可。
3. 上层评测逻辑、学生 Agent 写法、材料生成脚本都不需要改。

## 学生 Agent API

学生文件必须放在 `students/` 目录下，并且每个文件都要定义一个名为 `Agent` 的类。

最小合法示例：

```python
from debate_eval.api import BaseAgent


class Agent(BaseAgent):
    def argue(self, chat_history):
        return self.chat(
            history=chat_history,
            user_prompt=(
                f"请作为{self.side}继续辩论。\n"
                f"辩题：{self.topic}\n"
                f"材料：{self.material}\n"
                "请结合材料和对手最新观点，只输出一句中文发言。"
            ),
        )
```

### 学生必须实现的方法

- `argue(chat_history) -> str`

含义：

- 输入：当前轮次可见的 `chat_history`
- 输出：当前 Agent 本轮发言的一句话字符串

### 学生可直接使用的字段

- `self.side`
  - 当前立场，取值为 `"affirmative"` 或 `"negative"`
- `self.topic`
  - 当前辩题
- `self.material`
  - 当前整篇材料正文

### 学生可调用的方法

- `self.chat(messages=None, *, system_prompt=None, user_prompt=None, history=None) -> str`

推荐用法是：

```python
return self.chat(
    history=chat_history,
    user_prompt="请继续辩论，只输出一句中文发言。",
)
```

`chat()` 支持两种常见调用方式：

1. 直接传 `history` 和 `user_prompt`
2. 直接传完整 `messages`

示例：

```python
return self.chat(
    messages=[
        {"role": "system", "content": "你是正方辩手。"},
        {"role": "user", "content": "请输出一句回应。"},
    ]
)
```

### chat_history 的格式

`chat_history` 是一个标准 chat template 列表，每项都是一个字典：

```python
[
    {"role": "system", "content": "..."},
    {"role": "assistant", "content": "..."},
    {"role": "user", "content": "..."},
]
```

在学生视角下：

- `system`: 当前辩题、材料、立场说明
- `assistant`: 自己之前各轮的历史发言
- `user`: 对手之前各轮的历史发言，以及你当前追加的提问提示

也就是说，学生在 `argue(chat_history)` 中已经能拿到：

1. 当前辩题
2. 完整材料
3. 自己之前说过什么
4. 对手之前说过什么

### 兼容方法

当前 `BaseAgent` 里还保留了以下兼容接口：

- `foward(...)`
- `forward(...)`
- `generate(...)`

它们是为了兼容旧写法保留的。当前项目的真实推荐写法是只使用 `chat()`。

## 学生文件合法性要求

评测器会检查：

1. 文件是否位于 `students/`
2. 文件是否是 `.py`
3. 是否定义 `Agent` 类
4. `Agent` 是否继承 `debate_eval.api.BaseAgent`
5. 是否实现 `argue(self, chat_history)`
6. `Agent` 是否能被正常实例化

不满足时，会在验证阶段直接显示 `INVALID` 及错误原因。

## 材料格式要求

材料文件放在 `materials/` 下。

当前支持：

- `.txt`
- `.md`
- `.json`

对于 `.txt` / `.md`：

- 第一行：辩题
- 第二行开始：材料正文

例如：

```text
人工智能应当在大学课程中替代部分基础作业批改
支持方可强调效率、公平和反馈速度；反对方可强调学习过程被削弱、误判风险和教育责任不可完全外包。
```

对于 `.json`：

- 可以是一个对象，也可以是对象数组
- 每个对象建议包含：
  - `topic`
  - `content`

## 评测流程

一次完整评测流程如下：

1. 读取并验证 `students/` 中的所有 Agent。
2. 读取 `materials/` 中的所有材料。
3. 如果没有传 `--material`，随机抽取 1 篇材料。
4. 正方先发言，反方后发言。
5. 总共进行 `--rounds` 轮，默认 10 轮。
6. 每轮发言后立即输出到终端。
7. 辩论结束后，将完整记录发给裁判模型。
8. 裁判模型只输出：
   - `affirmative`
   - 或 `negative`
9. 如果裁判没有返回可解析结果，则回退为随机判定，并在输出中标明。

## 裁判 prompt

当前裁判 prompt 在 `debate_eval/engine.py` 中构造，逻辑是两段式：

1. `system` 中写入裁判身份和裁决标准
2. 在整场辩论记录后，再追加一个最终裁决提示，要求只输出 `affirmative` 或 `negative`

裁判重点考察：

1. 是否紧扣辩题与材料
2. 是否论证清晰、有逻辑
3. 是否有效回应和反驳对手
4. 是否存在明显漏洞、偷换概念、重复空话
5. 哪一方整体攻防质量更强

## 运行方式

### 1. 只验证学生代码是否合法

```bash
python -m debate_eval.cli --validate-only
```

### 2. 用材料库中随机一篇材料进行完整辩论

```bash
python -m debate_eval.cli
```

### 3. 指定某一篇材料进行辩论

```bash
python -m debate_eval.cli --material sample_topic.txt
```

### 4. 指定轮数

```bash
python -m debate_eval.cli --material sample_topic.txt --rounds 10
```

### 5. 固定随机种子

这个随机种子会影响：

- 默认随机抽取材料
- 裁判无法解析时的随机回退结果

```bash
python -m debate_eval.cli --seed 7
```

## 终端输出说明

完整运行时，终端会输出：

1. 学生文件验证结果
2. 当前使用的材料
3. 双方每一轮发言
4. 裁判原始输出
5. 是否使用裁判回退
6. 最终胜负
7. 使用统计

典型输出格式如下：

```text
Validation results:
- example_affirmative: VALID (OK)
- example_negative: VALID (OK)

Debate results:
== Material: sample_topic.txt | Topic: ... ==
Matchup: example_affirmative (affirmative) vs example_negative (negative)
Round 01 [affirmative] affirmative: ...
Round 01 [negative] negative: ...
...
Judge raw output: affirmative
Judge fallback used: False
Final winner: affirmative
Summary: example_affirmative vs example_negative | winner=affirmative | ...
```

如果你想把整段终端输出保存下来，可以直接用重定向：

```bash
python -m debate_eval.cli --material sample_topic.txt --rounds 10 > debate_output.txt
```

## 生成材料

可以使用 `gen_materials.py` 真实调用材料生成模型，批量生成辩论材料。

### 基本命令

```bash
python gen_materials.py --prompt "围绕教育、科技治理与公共政策生成高质量辩论材料" --count 3
```

### 可用参数

- `--prompt`
  - 生成材料的高层任务描述
- `--count`
  - 生成多少篇材料
- `--output-dir`
  - 输出目录，默认 `materials`
- `--prefix`
  - 输出文件名前缀，默认 `generated_material`

### 输出文件格式

生成后的文件名格式默认如下：

```text
generated_material_001.txt
generated_material_002.txt
generated_material_003.txt
```

### 材料生成目标

`gen_materials.py` 中的 prompt 明确要求生成的材料满足：

1. 足够长
2. 信息密度高
3. 正反双方都能从中抽取论据
4. 材料中存在利益冲突、边界条件、例外情形、潜在风险
5. 不能只靠抓住单一句子辩论
6. 必须通读全文并综合多处信息，才能打出高质量攻防

## 关键实现文件

- `utils.py`
  - 统一模型配置与 API 调用入口
- `debate_eval/api.py`
  - 学生可继承的 `BaseAgent` 和 `StudentAPI`
- `debate_eval/loader.py`
  - 学生 Agent 发现与合法性校验
- `debate_eval/engine.py`
  - 对战引擎、材料读取、裁判逻辑
- `debate_eval/cli.py`
  - 命令行入口
- `gen_materials.py`
  - 长辩论材料生成脚本

## 当前推荐使用方式

如果你是课程教师或助教，最常见的流程是：

1. 先用 `gen_materials.py` 生成一批材料到 `materials/`
2. 收集学生的 Agent 文件到 `students/`
3. 用 `python -m debate_eval.cli` 随机抽题评测
4. 如需复现实验，记录 `--material` 和 `--seed`
5. 如需存档，直接把终端输出重定向到 `.txt`

## 注意事项

1. 当前学生侧推荐只使用 `chat()`，不要再依赖旧的 `generate()` 工作流。
2. 当前裁判模型要求只输出 `affirmative` 或 `negative`，否则系统会尝试回退。
3. 如果你修改了模型名、供应商地址或鉴权方式，请只改 `utils.py`。
4. 如果你想更改辩论规则、轮数默认值、裁判 prompt，请改 `debate_eval/engine.py`。
