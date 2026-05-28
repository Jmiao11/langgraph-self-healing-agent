# 架构设计

## 1. 项目目标与边界

### 1.1 核心目标

本项目针对 LLM Agent 在真实业务环境下的若干工程不确定性——工具调用失败、工具幻觉、权限越界、提示词注入等——构建一套具备自愈能力、多智能体路由与多层安全判定的 LangGraph 系统，旨在验证『Production-grade LLM Agent 应当具备哪些工程化设计』这一命题。

### 1.2 场景选型理由

1. 自习室有明确的业务规则，系统据此触发 `business_rule_violation` 分类、向用户合规拒答。
2. 自习室有资源争抢（座位有限），能触发 `resource_conflict`，验证乐观锁 / CAS（Compare-And-Swap）和自愈功能。
3. 有用户身份概念，验证防止用户越权，进行安全设置。
4. 既有结构化数据（座位 / 订单 SQL 表）又有非结构化数据（规章制度文档），能在同一项目内同时验证工具调用与 RAG 检索。

### 1.3 技术目标

本项目按以下三层组织技术目标：

**核心能力（项目主要卖点）**

1. **Self-Healing Agent 的工程化设计**：包含基于 LLM 的错误语义分类、Classify-then-Decide 双阶段决策、自愈次数熔断三个子机制。

**支撑能力（工程基础盘）**

1. **多层身份隔离的安全防御**:API 认证层 → 工具签名层 → 服务层的三道闸门。
2. **LangGraph 多子图编排与状态总线设计**:6 维 AgentState + 自定义 reducer + 全链路 trace。
3. **双路 RRF 融合的 RAG 检索**:BM25 字面量 + 向量语义 + LLM 自动元数据打标。

**工具集成能力**

1. **MCP 协议接入与 Service 层异常映射**:LLM 工具失败的标准化路径。
1. - **完整 CRUD + 越权防护**：booking 子图实现订单的 Create / Read / Update / Delete 全流程，配套 cancel_booking 的跨表原子事务（同时更新 bookings 和 seats）+ "存在 → 归属 → 状态" 三段式校验顺序，确保越权请求不暴露资源存在性。

### 1.4 已知限制与未来工作 (Out of Scope)

本项目刻意将以下事项划在范围外，原因均为"不会触发新的架构挑战"：

| 限制项               | 现状                                                | 升级到生产级需要补充                                         |
| -------------------- | --------------------------------------------------- | ------------------------------------------------------------ |
| **CRUD 完整度**      | 已实现完整 CRUD + 越权防护层。                      | 暂无需进一步升级                                             |
| **数据库并发能力**   | SQLite + WAL，可支持单机轻并发                      | 替换为支持行锁的 PostgreSQL/MySQL，并补充并发压测            |
| **多 Provider 兜底** | LLM 池仅注册 Moonshot Kimi 一个 provider            | 架构上已通过 `init_llm_pool` 工厂函数预留扩展点，未实际验证 GPT/Claude 接入 |
| **测试覆盖**         | 仅有 summarize 节点的单元测试，其余依赖手动黑盒验证 | 补充 LLM mock 框架，对错误分类器、路由决策、状态总线做单元覆盖 |



## 2. 项目分层

本项目采用四层架构：

1. **用户接入层**（`api.py`, `app.py`）：接 HTTP 请求和 UI，做认证，不写业务逻辑。

2. **编排层**（`graphs/`）：基于 LangGraph，负责理解用户意图、派发到对应子图、管理对话状态和流转。是项目最复杂的一层。

3. **业务服务层**（`services/`）：把基础设施提供的原始能力包装成有业务语义的方法，注入业务逻辑（比如异常映射、RRF 融合排序）。

4. **基础设施层**（`infrastructure/`, `mcp_server/`, `data/`）：提供原始能力——LLM 实例、向量库、SQLite 持久化、MCP 工具，不知道这是个自习室项目。

   

## 3. 核心设计决策

### 3.2 Self-Healing Agent 的架构演进

#### 3.2.1 问题陈述：为什么需要 Self-Healing？

我的自习室场景下，工具调用失败有四种典型样态：资源被抢（座位 `SEAT_OCCUPIED`）、业务规则拦截（`VIOLATION_LIMIT` 违约超限）、参数越界（duration 超过 8 小时）、底层抖动（SQLite 锁库）。

这四种失败的处理路径完全不同——前两种用户能修，第三种 Agent 自己能修，第四种重试就能修。如果不显式处理，Agent 会把所有错误码当成自然语言扔回上下文里继续推理，结果要么陷入死循环，要么向用户编造一条"订单已生成"的虚假回复。Self-Healing 就是为了把这四类失败拆开，在代码层分别给出确定性的处理策略。

#### 3.2.2 V1：让 LLM 全权决策（含失败案例）

在最初的 V1 版本中，我犯了一个典型的工程错误：过度信任大模型，让 LLM 充当了全权决策者。

当时我设计了一个 `RepairDecision` 数据结构，让 LLM 在捕获异常后同时输出四项内容：

```python
class RepairDecision(BaseModel):
    reasoning: str                  # 错误推理
    action_type: Literal[...]       # 处理动作（已用 Literal 锁住选项）
    suggested_tool: str             # 建议调用的工具
    instruction_to_agent: str       # 给 Agent 的指令
```

实测中这个设计在 `VIOLATION_LIMIT`（违约超限）场景下翻车——LLM 一次推理里同时犯了两类错误：

- `reasoning`: "该限制属于业务硬规则，无法通过重试、换接口或调整参数绕过"
- `action_type`: `"retry_with_new_params"` ← 跟自己的 reasoning 直接矛盾
- `suggested_tool`: `"violation_service::query_violation_list"` ← 幻觉，编造了工具名

这次翻车让我意识到一个本质问题：LLM 极度擅长"语义分析"，但极度不擅长"确定性决策"。让它在同一个节点既做理解又下决策，分裂是必然的。

#### 3.2.3 V2：Classify-then-Decide 关注点分离

为解决 V1 的幻觉和自相矛盾，我重构了整个决策链路，核心动作是：剥离 LLM 的决策权，只保留其分类权。

我将 `RepairDecision` 替换为 `ErrorClassification` 结构，砍掉了负责决策的 `action_type` 和自由发散的 `suggested_tool` 字段。现在，LLM 只需要回答"这是什么类型的错误"：

```python
class ErrorClassification(BaseModel):
    reasoning: str
    category: Literal[
        "business_rule_violation",
        "resource_conflict",
        "invalid_params",
        "transient_failure",
        "unrecoverable"
    ]
    user_facing_summary: str
```

被剥离出的决策权，在代码层引入的一张静态字典 `REPAIR_STRATEGY_MAP` 接手。LLM 输出 `category` 后，代码查表给出确定性策略：

```python
REPAIR_STRATEGY_MAP = {
    "business_rule_violation": {
        "should_retry": False,
        "instruction": "向用户解释原因，禁止重试..."
    },
    "resource_conflict": {
        "should_retry": True,
        "instruction": "使用 search_free_seats 查询可用资源..."
    }
}
```

我把这种架构称为 Classify-then-Decide（先分类后决策）。它的本质洞察是：让 LLM 分类错误类型，让代码回答如何解决。因为 `category` 被 `Literal` 严格锁死，LLM 无法编造不存在的错误类型；而因为策略表是硬编码的，分类结果一旦落地，下游的重试与兜底行为就不再受大模型幻觉的影响。

#### 3.2.4 V3：Prompt 边界锚定（含失败案例）

V2 改完后，我以为问题彻底解决了，但在第二个测试场景就翻车了。

在测试"座位被抢"（`SEAT_OCCUPIED`）错误时，LLM 给出的分类竟然是 `business_rule_violation`。它的推理逻辑是："座位状态不对，这属于业务规则层面的冲突"。

这次翻车暴露了一个隐蔽的问题：即使 Literal 锁死了输出空间，LLM 对这些概念的**语义边界**依旧会出错。在它的语料认知里，"资源不可用"和"违反业务规则"被混为一谈。如果分类第一步错了，V2 精心设计的策略表就会把系统带向深渊——判定为业务违规会直接熔断并拒答，而实际上这只是资源冲突，调工具换个座位就能解决。

针对这个问题，我在 `error_analyzer_node` 的系统 Prompt 中引入了边界锚定，构建了四层防御：

1. **头对头对比**：明确界定 `business_rule` 针对的是"用户身份/账户状态"，而 `resource_conflict` 针对的是"所请求的物理资源"。

2. **判断口诀**：强行注入一个思考锚点——"换个对象（如换个座位）重试有用吗？"有用就是资源冲突，没用就是业务限制。

3. **反例对照**：直接在 Prompt 里写死特例（明确指出 `SEAT_OCCUPIED` 几乎必然是 `resource_conflict`）。

4. **兜底偏置**：规定拿不准时优先选 `unrecoverable`（保守策略，宁可误终止不可误重试）。

   

#### 3.2.5 V4 演进方向：用代码确定性短路 LLM

V3 跑通后，self-healing 链路在功能上已经闭合，但在原则上还有一处未贯彻的地方。

每一次工具调用失败，error_analyzer_node 都会触发一次 LLM 调用来做错误分类，即便这个错误是系统中早已定义好的已知异常（如 SEAT_OCCUPIED、VIOLATION_LIMIT），耗费Token。 对于每一个在 BookingDomainError 中已经携带了明确 category 元数据的异常，V3 仍然绕了一大圈——把代码已经知道答案的结构化元数据，交给 LLM 用自然语言重新推理一遍，再得出一个原本查表就能得到的答案。V2 已经把决策权交还给代码，但 V3 在分类那一步又把不确定性引了回来——原则只在部分路径上贯彻，不算成立。 

顺着这个反思往下看，V3 中 LLM 的冗余其实不止"分类"一处。V3 让 LLM 在 ErrorClassification 中同时输出 category 和 user_facing_summary，背后的设计假设是——工具层抛出的错误是给开发者看的技术描述，需要 LLM 翻译成用户能理解的语言。但回看 mcp_server 的实际实现，所有 message 字段本就是用户友好的中文描述（如"座位 1 当前已被占用"），LLM 的翻译职责从一开始就不成立。这是 V3 时期一个从未被审视的潜在假设——不是实现层面的疏漏，而是设计层面的错误前提。

为此，V4 做了三处协同改动：

1. **工具层透传元数据**：book_seat_tool 捕获 BookingDomainError 时，将 e.category.value 与 error_code、message 一起序列化进 [TOOL_ERROR] 字符串：[TOOL_ERROR] category=resource_conflict, error_code=SEAT_OCCUPIED, message=座位 1 当前已被占用

2. **error_analyzer 旁路判定**：节点入口先用正则提取 category 字段。命中 REPAIR_STRATEGY_MAP 中已知分类时，直接查策略表跳过 LLM 调用，并用工具层 message 字段填充 instruction_template 中的 {user_summary} 占位符。

3. **未知异常降级**：仅在异常未携带 category 元数据时（如未来新增的、尚未被领域异常体系覆盖的错误），才降级到 V3 的 LLM 语义分类作为兜底。

**实测验证：**

用户预定占用座位触发 SEAT_OCCUPIED 时，日志显示"⚡ [Self-Healing V4] 异常元数据短路：category=resource_conflict（0 LLM 调用）"，trace 中 llm_called 字段为 false。所有已知业务异常（SEAT_OCCUPIEDVIOLATION_LIMIT、INVALID_PARAM 等）在 error_analyzer 阶段实现 0 LLM 调用，仅当出现未预见的底层报错时才走 LLM 兜底分类。



V4 的本质，是承认 V2 确立的"代码确定性 > LLM 不确定性"原则，只有在所有路径上都贯彻才算真正成立。至此，self-healing 链路上所有已知异常都不再依赖 LLM 参与——这也是下一节将要总结的设计原则能够立得住的真实落点。



#### 3.2.6 设计原则提炼

本项目从 V1 到 V4 的演进，本质上是为了控制大模型带来的不确定性，不断挤压大模型的自由发散空间，将控制权彻底收归确定性代码的轨迹。

LLM 在 Agent 链路中的唯一合法身份，是处理不可预见输入的"模糊语义翻译器"——负责在用户和系统报错的非结构化文本中提取结构化事实。而所有触及状态流转、动作决策和系统边界校验的操作，都必须由代码层确定性地完成。

这一原则在本项目中被彻底贯彻为三个具体动作：剥离决策权的 Classify-then-Decide 架构、用 Prompt 强制锁死认知空间的边界锚定，以及用异常元数据消除冗余推理的 V4 短路路由。每一个动作，都在剥夺 LLM 不该拥有的权力。

这件事远超出自习室场景的意义在于：它让我看清了 LLM 应用工程化的一个核心约束——系统的健壮性从来不取决于大模型有多聪明，而取决于代码的防御底线有多硬。作为一名 AI 工程师，我的工作不是去教大模型怎么做决策，而是写好那些确定性代码——哪怕大模型完全疯掉，系统也不会崩溃。
