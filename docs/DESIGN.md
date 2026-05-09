### 1.1 核心目标

本项目针对 LLM Agent 在真实业务环境下的若干工程不确定性——工具调用失败、工具幻觉、权限越界、提示词注入等——构建一套具备自愈能力、多智能体路由与多层安全判定的 LangGraph 系统，旨在验证『Production-grade LLM Agent 应当具备哪些工程化设计』这一命题。

### 1.2 场景选型理由

1，自习室有明确的业务规则，系统据此触发 business_rule_violation 分类、向用户合规拒答"

2，自习室有资源争抢（座位有限），能触发resource_conflict，验证乐观锁/CAS，和自愈功能

3，有用户身份概念，验证防止用户越权，进行安全设置

4，既有结构化数据（座位/订单 SQL 表）又有非结构化数据（规章制度文档），能在同一项目内同时验证工具调用与 RAG 检索"。

### 1.3 技术目标

本项目按以下三层组织技术目标：

**核心能力（项目主要卖点）**

1. **Self-Healing Agent 的工程化设计**：包含基于 LLM 的错误语义分类、Classify-then-Decide 双阶段决策、自愈次数熔断三个子机制。

**支撑能力（工程基础盘）**

2. **多层身份隔离的安全防御**：API 认证层 → 工具签名层 → 服务层的三道闸门。 
3. **LangGraph 多子图编排与状态总线设计**：6 维 AgentState + 自定义 reducer + 全链路 trace。 
4. **双路 RRF 融合的 RAG 检索**：BM25 字面量 + 向量语义 + LLM 自动元数据打标。

**工具集成能力** 

5. **MCP 协议接入与 Service 层异常映射**：LLM 工具失败的标准化路径。



### 1.4 已知限制与未来工作 (Out of Scope)

本项目刻意将以下事项划在范围外，原因均为"不会触发新的架构挑战"：

| 限制项                  | 现状                                                | 升级到生产级需要补充                                         |
| ----------------------- | --------------------------------------------------- | ------------------------------------------------------------ |
| **Booking CRUD 完整度** | 仅实现 Create 流程                                  | Read/Update/Delete 属于已实现工具的同质变体（同样的 MCP 工具模式 + 事务逻辑 + 错误分类策略），新增它们不会触发新的架构挑战，工作量约 0.5 天 |
| **数据库并发能力**      | SQLite + WAL，可支持单机轻并发                      | 替换为支持行锁的 PostgreSQL/MySQL，并补充并发压测            |
| **多 Provider 兜底**    | LLM 池仅注册 Moonshot Kimi 一个 provider            | 架构上已通过 `init_llm_pool` 工厂函数预留扩展点，未实际验证 GPT/Claude 接入 |
| **测试覆盖**            | 仅有 summarize 节点的单元测试，其余依赖手动黑盒验证 | 补充 LLM mock 框架，对错误分类器、路由决策、状态总线做单元覆盖 |



## 口述版：

#### §1.1 项目目标（45秒）

> "嗯，这个项目想解决一个很实际的问题。我们都知道现在 LLM 调工具不太靠谱，有四类典型的坑：
>
> 第一是**工具调用失败**——比如座位被占、违约超限，工具返回错误，Agent 不知道怎么处理；
>
> 第二是**工具幻觉**——LLM 会编一个不存在的工具名出来调用，或者编错参数；
>
> 第三是**权限越界**——用户故意说『我是另一个学号』，让 LLM 用别人的账号下单；
>
> 第四是 **prompt injection**——用户用提示词攻击让 LLM 越界。
>
> 我用 LangGraph 搭了一个多 Agent 系统来处理这四类问题，验证一个 production-grade 的 LLM Agent 工程上到底要做哪些事。"

#### §1.2 场景选型（30秒）

> "选自习室管理这个场景，是因为它有几个适合验证 Self-Healing Agent 的特征：
>
> 一是有**明确的业务硬规则**，比如违约次数上限，能触发『业务规则拒绝』这类错误；
>
> 二是有**资源争抢**，座位数量有限，能触发『资源冲突』，验证乐观锁和自愈策略；
>
> 三是有**明确的用户身份**，能验证越权防御；
>
> 四是**结构化数据和非结构化数据并存**——座位订单是 SQL 表，规章制度是文档——能在同一项目里同时验证工具调用和 RAG 检索。"

#### §1.3 技术目标（60秒，**重点改了**）

> "这个项目我分了三层目标：
>
> **核心能力**是 **Self-Healing Agent 的工程化设计**，包含三个子机制：① 用 LLM 做错误语义分类（5 类），但**只让它分类，不让它决策**——决策由代码层查策略表完成，这是个 Classify-then-Decide 的双阶段架构；② 自愈次数熔断，防止无限重试导致级联故障；③ 全链路 trace 把决策路径记下来，方便调试。
>
> **支撑能力**有三块：
>
> 第一是**多层身份隔离**——不是靠 prompt 软约束，是靠**工具签名层物理隔离**：我把 student_id 参数直接从工具签名里删掉，用 Python 闭包从 AgentState 捕获认证身份，LLM 根本不可能传别人的学号。
>
> 第二是 **LangGraph 多子图编排**——6 维状态总线 + 自定义 reducer 支持轮次级 trace 清零。
>
> 第三是**双路 RRF 融合的 RAG 检索**——BM25 字面量召回 + 向量语义召回 + LLM 自动元数据打标，用 RRF 融合排序。
>
> **工具集成层**是 MCP 协议接入 + Service 层异常映射——把 LLM 工具失败的原始错误码翻译成 Python 标准异常。"

#### §1.4 已知不足（30秒）

> "这个项目我刻意没做几件事：
>
> 第一，**Booking 只实现了 Create**，没做 Read/Update/Delete——因为这些都是已实现工具的同质变体，不会触发新的架构挑战，工作量大概半天；
>
> 第二，**没做数据库并发压测**——目前是 SQLite + WAL 模式，生产场景需要换成 PostgreSQL；
>
> 第三，**LLM Pool 只接了 Kimi 一家 provider**，但架构上通过 init_llm_pool 工厂函数预留了切换扩展点，没实际验证 GPT/Claude；
>
> 第四，**单元测试覆盖不足**，目前只有 summarize 节点有完整单测，其他靠手动黑盒验证。"
>
> 

我的项目分四层：

1. **用户接入层**（api.py, app.py）：接 HTTP 请求和 UI，做认证，不写业务逻辑。
2. **编排层**（graphs/）：基于 LangGraph，负责**理解用户意图**、**派发到对应子图**、**管理对话状态和流转**。是项目最复杂的一层。
3. **业务服务层**（services/）：把基础设施提供的原始能力**包装成有业务语义的方法**，注入业务逻辑（比如异常映射、RRF 融合排序）。
4. **基础设施层**（infrastructure/, mcp_server/, data/）：提供原始能力——LLM 实例、向量库、SQLite 持久化、MCP 工具，不知道这是个自习室项目。

#### Q2：BookingService.book() 被谁调用？调用谁？

你答："被编排层使用，调用基础设施层"。

✅ 大方向对。但**面试官追问时，你要能说出"编排层的哪个具体节点"**。

完整答案：

> "BookingService.book() 被编排层的 booking_self_healing_subgraph 里的 book_seat_tool 调用——这是个 LangChain @tool 装饰的函数，作为 LLM 的工具暴露给 booking_agent。它本身调用的是基础设施层的 MCP server 暴露的 book_seat_transaction 工具。所以完整的调用链是：booking_agent (LLM 决策) → book_seat_tool (LangChain 工具) → BookingService.book() (服务层) → MCP book_seat_transaction (基础设施)。"

**这一段调用链你必须能背**。面试官最爱问"你这个工具是怎么被调到的"，能把这条链讲清楚的人，立刻被划进"懂工程的"那一档。





## ✅什么叫"工具幻觉"？

非常好的问题。你能问出这个，说明你**没有在背稿**，是真的在思考。

而且这个问题命中了你项目里**第二个最有面试杀伤力的设计**（仅次于身份隔离）。

让我们一步步把它拆清楚。

------

## 先回到原点：什么叫"工具幻觉"？

**工具幻觉** = LLM 在做工具调用时，凭空捏造一些不存在的东西。具体有三种形式：

| 类型           | 表现                                                      | 你项目里有没有遇到过？                 |
| -------------- | --------------------------------------------------------- | -------------------------------------- |
| **工具名幻觉** | LLM 调用一个根本不存在的工具，比如 `query_violation_list` | ✅ Step 2.5 之前真的遇到过              |
| **参数名幻觉** | 工具是真的，但 LLM 编了个不存在的参数名                   | 没遇到过（被 LangChain Pydantic 拦了） |
| **参数值幻觉** | 参数名对，但值是编的，比如 student_id 编一个别人的        | ✅ Step 1 之前的越权风险本质就是这个    |

你的项目对这三种**各有不同的防御机制**。这正是这个项目的工程深度所在。我们一个个看。

------

## 防御 1：防"工具名幻觉" - 用 Literal 类型枚举锁死

**回顾真实案例**：

Step 2.5 之前，你的`error_analyzer_node`是这样定义LLM输出结构的：

```python
class RepairDecision(BaseModel):
    action_type: Literal["retry_with_new_params", "switch_tool", "ask_user", "abort"]
    suggested_tool: str = Field(default="", ...)  # ⚠️ 自由字符串
    instruction_to_agent: str = ...
```

注意 `suggested_tool` 是 `str`——**LLM 想填啥填啥**。

实测时它真的就编了一个 `violation_service::query_violation_list`，这个工具在你整个项目里**根本不存在**。

### 你怎么修的

Step 2.5 重构时，你**整个废掉了"让LLM建议工具"这个设计**，因为：

1. LLM 一旦能填自由文本，就会幻觉工具名
2. 即使用 `Literal` 把工具名枚举锁死，LLM 也只是"分类"了一下，不是真的"决策"
3. 真正的决策应该由**代码层查策略表**完成，根本不需要 LLM 推荐工具

所以新设计 `ErrorClassification` 里**完全没有"建议工具"字段**：

```python
class ErrorClassification(BaseModel):
    reasoning: str
    category: Literal[
        "business_rule_violation",
        "resource_conflict",
        "invalid_params",
        "transient_failure",
        "unrecoverable"
    ]   # ⭐ 只能在这5个里选，物理上不可能幻觉
    user_facing_summary: str
```

LLM 的输出空间被 **Pydantic + Literal** 锁死成 5 个选项。"工具名幻觉" 这个问题被**架构性消除**了——不是"防御"，是直接**让它不可能发生**。

### 面试时这样讲（30秒）

> "工具名幻觉这个问题，我项目里其实做了一次架构重构。最早我让 LLM 自由建议下一步该调哪个工具，实测发现它会编一个不存在的工具名出来。后来我意识到根因不是『LLM 不靠谱』，而是『不该让 LLM 做决策』——LLM 应该只负责语义理解。所以我把架构重构成 **Classify-then-Decide 双阶段**：LLM 只做错误分类，输出空间用 Pydantic 的 Literal 枚举锁死成 5 个有限选项；处理策略由代码层查策略表确定性决定。这样工具名幻觉在架构上就不可能发生了。"

------

## 防御 2：防"参数名幻觉" - LangChain @tool 装饰器的天然保护

这个不是你主动做的，是**框架免费送的**。但面试时也要会讲。

```python
@tool
async def book_seat_tool(seat_id: int, duration: int) -> str:
    """执行座位预定..."""
```

`@tool` 装饰器会自动生成 JSON Schema 给 LLM：

```json
{
  "name": "book_seat_tool",
  "parameters": {
    "type": "object",
    "properties": {
      "seat_id": {"type": "integer"},
      "duration": {"type": "integer"}
    },
    "required": ["seat_id", "duration"]
  }
}
```

LLM 看到这个 schema，输出 JSON 时被强制约束在 `seat_id` 和 `duration` 这两个键上。如果 LLM 真的编一个 `seat_number` 参数，**LangChain 在解析阶段就会报 `ValidationError`**，根本不会调用到底层。

### 面试时简短带过即可

> "参数名幻觉这一层，LangChain 的 @tool 装饰器会从函数签名自动生成 JSON Schema，LLM 输出的 tool_calls 会被 Pydantic 强校验。参数名编错了在解析阶段就会被拦下，根本到不了 service 层。"

------

## 防御 3：防"参数值幻觉" - 工具签名层物理隔离（你的 Step 1）

**这是面试官最可能深挖的一个，你必须讲透。**

参数名是对的，但参数**值**可能被 LLM 编。最危险的就是 `student_id`：

```python
# ❌ 改造前
@tool
async def book_seat_tool(student_id: str, seat_id: int, duration: int):
    """执行座位预定，必须明确传入学号..."""
```

LLM 看到 `student_id: str`，它就以为"哦我可以填一个 student_id"。 用户对话里说"我是 stu_bad，帮我下单"——LLM 真的可能就听他的，传 `student_id="stu_bad"` 进来。这就是**参数值幻觉导致的越权**。

### 你怎么修的（Step 1）

```python
# ✅ 改造后：工具签名里根本没有 student_id 参数
def make_tools_for_user(authenticated_sid: str):  # ← 闭包捕获认证身份
    @tool
    async def book_seat_tool(seat_id: int, duration: int) -> str:  # ← 签名里没有 student_id
        """执行座位预定..."""
        # 强制使用闭包里的认证身份，无视 LLM 任何输入
        data = await booking_service.book(authenticated_sid, seat_id, duration)
```

**为什么这能防住幻觉**：

1. LLM 看到的工具 schema 里**根本没有 student_id 这个参数**——它想编也没地方编
2. 真正的 student_id 是 Python 闭包从 `AgentState["student_id"]` 里捕获的——这个值在用户登录时就被注入，对话过程中无法修改
3. 即使 LLM 在对话里被用户骗了，决定"我要帮 stu_bad 下单"，它**物理上没法把这个想法表达出来**——工具签名只接受 `seat_id` 和 `duration`

这就是从 **Prompt-level 软约束** → **代码-level 物理隔离** 的升级。

### 面试时这样讲（45秒）

> "参数值幻觉里最危险的一种是身份相关的参数。最早我的工具签名是 `book_seat_tool(student_id, seat_id, duration)`，student_id 由 LLM 自己填。我用 prompt 反复强调『必须用当前用户的学号』，但 prompt 是软约束——如果用户在对话里说『我是另一个学号』，LLM 就有可能听他的，造成越权。
>
> 我的做法是把 student_id **直接从工具签名里删掉**，改成 `book_seat_tool(seat_id, duration)`。真正的 student_id 用 Python 闭包从 AgentState 捕获——这个值在 API 层认证通过后注入，对话过程中无法修改。
>
> 这样防御就从 prompt-level 升级到了代码-level：LLM 看到的 schema 里压根没有 student_id 这个参数，它想编也没地方编。即使 prompt injection 把它骗到了，物理上也没法越权。"

------

## 总结一张表（面试时心里默念这张表）

| 幻觉类型           | 防御机制                                           | 设计层次       |
| ------------------ | -------------------------------------------------- | -------------- |
| 工具名幻觉         | Pydantic Literal 枚举（Classify-then-Decide 架构） | 架构级消除     |
| 参数名幻觉         | LangChain @tool 自动 JSON Schema                   | 框架级防御     |
| 参数值幻觉（身份） | 工具签名层移除 + 闭包捕获认证身份                  | 代码级物理隔离 |

**注意这三层的递进**：

- 第一层是**架构选择**（不让LLM做决策）
- 第二层是**框架红利**（用LangChain就有）
- 第三层是**主动设计**（你Step 1的核心成果）

讲面试时按这个顺序讲——从抽象到具体，从框架到自创——会显得很有层次感。

------

## ✋ 现在请你做

**任务 1**：用你自己的话**口述一遍**这三层防御。可以参考我上面的"面试时这样讲"，但要用你的措辞。

**任务 2**：回答我两个问题，确认你真懂了：

**Q1**：如果一个面试官追问你——"你说工具签名删掉 student_id 防越权，那 service 层执行的时候不还是要 student_id 吗？这个值哪来的？"——你怎么答？

**Q2**：如果面试官追问——"为什么你不直接在 service 层做权限校验，要在工具签名层做？"——你怎么答？

这两个问题如果你答上来了，说明这个机制你真懂了，可以进 §2。 答不上来也没关系，告诉我，我帮你想清楚。





## ✅**RRF 融合**

#### 全称是 **Reciprocal Rank Fusion（倒数排序融合）**

它是一种在信息检索（Search & Information Retrieval）领域非常经典且极具实操价值的算法。简单来说，RRF 的作用是：**将多个不同的搜索引擎或检索算法给出的多个排序结果，公平地融合成一个最终的、更优的排序列表。**

在当今非常火热的大模型 RAG（检索增强生成）应用中，RRF 几乎是“混合检索（Hybrid Search）”的标配。

以下是关于它的核心原理解析：

### 1. 为什么要用 RRF？（解决的核心痛点）

在混合检索中，我们通常会同时使用两套检索系统：

- **向量检索（Vector Search）：** 擅长理解语义（例如搜“苹果手机”，能搜出“iPhone”）。它给出的分数通常是余弦相似度（如 0.85、0.92）。
- **关键词检索（BM25）：** 擅长精准匹配（例如必须要包含特定的产品型号或专有名词）。它给出的分数是基于词频计算的（如 15.4、23.8）。

**痛点在于：这两套系统的“分数”完全不在一个维度上，无法直接相加或比较。** 0.85 的向量相似度并不等同于 0.85 的 BM25 分数。如果强行做分数归一化（Normalization），很容易因为异常极值导致结果失真。

RRF 就是为了解决“分数不可比”的问题而诞生的。**它完全抛弃了原始得分，只看文档在各自列表中的“排名（Rank）”。**

### 2. RRF 的计算公式

RRF 的核心思想是：排名越靠前的文档，得分越高，但得分衰减的速度是平缓的。它的公式非常简单：

$RRF\_Score = \sum_{i\in R} \frac{1}{k + rank_i}$

- **$rank_i$**：指的是某篇文档在第 $i$ 个检索结果列表中的**排名**（第 1 名就是 1，第 5 名就是 5）。
- **$k$**：是一个平滑常数（Smoothing Constant）。在业内实践中，**$k$ 通常取值为 60**。如果一篇文档在某个列表中没有出现，则其排名趋于无穷大，该项得分为 0。

### 3. RRF 的偏好：为何它如此有效？

假设 $k=60$。我们来看看它在面临分歧时会偏向谁：

- **文档 A：** 在向量检索排第 1，在关键词检索排第 100。
  - 得分 = $1 / (60 + 1) + 1 / (60 + 100) \approx 0.01639 + 0.00625 = 0.02264$
- **文档 B：** 在向量检索排第 10，在关键词检索排第 10。
  - 得分 = $1 / (60 + 10) + 1 / (60 + 10) \approx 0.01428 + 0.01428 = 0.02856$

**结果是文档 B 打败了文档 A。**

这揭示了 RRF 最核心的智慧：**比起在某单一算法中表现极好但在另一算法中表现极差的“偏科生”，RRF 更偏爱在所有算法中表现都比较靠前的“全科生”。** 这种特性极大地提高了最终搜索结果的鲁棒性（Robustness）。
