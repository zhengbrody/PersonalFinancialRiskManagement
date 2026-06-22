# MLE / SDE 全栈学习与面试手册

> 目标:为明年的全职 **MLE / SDE** 求职做系统准备。
> 用法:这是一张「知识地图 + 面试清单 + 项目锚点」。每个主题给你 **① 要懂什么 ② 常被问什么 ③ 在 MindMarket 里对应哪段代码**。真实代码在仓库里,这份文档帮你把零散知识连成体系。
> 原则:**别背,要懂**。每个点问自己三问 —— 它解决什么问题?不这么做的代价?它的失败模式/极限?

---

## 0. 两条路线的区别(先想清楚你投哪个)

| | **SDE** | **MLE** |
|---|---|---|
| 核心 | 系统/服务/数据/可靠性 | 让模型在生产里持续有效 |
| 面试重点 | DSA + 系统设计 + 工程 | DSA(略少) + ML 基础 + ML 系统设计 |
| 2026 现实 | 后端/全栈/平台 | 很多岗是 **applied-AI / LLM 味** |
| 你的项目契合度 | ⭐⭐⭐ 直接能讲 | applied-AI ⭐⭐⭐;经典训练-服务 ⭐(需补一条 ML pipeline) |

**结论**:Part I–IV 是两条路共同的地基;Part V 是 MLE 专属;Part VI–VIII 是面试与项目讲法,两条路都要。

---

# Part I — 计算机基础(SDE + MLE 通用,面试地基)

## 1.1 数据结构与算法(DSA)—— 刷题的核心
**要懂**:
- 数据结构:数组/字符串、链表、栈/队列、哈希表、堆(优先队列)、树(BST/平衡树)、Trie、图、并查集(Union-Find)。
- 算法范式:双指针、滑动窗口、二分、回溯、DFS/BFS、动态规划(DP)、贪心、分治、拓扑排序、Dijkstra。
- 复杂度:时间/空间 Big-O,均摊分析(amortized,如动态数组扩容)。
**怎么练**:LeetCode 按 tag 刷(每个 tag 10–20 题),**Blind 75 / NeetCode 150** 是性价比最高的清单。先模式后题量。
**常被问**:手写 + 口述复杂度 + 边界条件 + 优化(从暴力到最优)。
**MindMarket 锚点**:`regime_detector` 里滑动窗口算波动率;`score_changes` 里 dict 做 O(1) 查找做持仓 diff(set 差集 = added/removed)。

## 1.2 操作系统
**要懂**:进程 vs 线程 vs 协程;内存(虚拟内存、栈/堆、GC);调度;**死锁**(4 条件 + 预防);文件/IO;Python 的 **GIL**(为什么 CPU 密集要多进程,IO 密集多线程/async)。
**常被问**:进程线程区别?死锁怎么避免?为什么 Python 多线程跑不满多核?
**MindMarket 锚点**:行情情绪打分用 `ThreadPoolExecutor`(IO 密集,GIL 不挡);Monte Carlo 是 CPU 密集,靠 NumPy(底层释放 GIL)向量化而非多线程。**OOM 事故**就是内存/虚拟内存知识的活例子。

## 1.3 计算机网络
**要懂**:OSI/TCP-IP 分层;TCP vs UDP;三次握手/四次挥手;HTTP/1.1 vs 2 vs 3、状态码、方法、幂等性;HTTPS/TLS 握手、证书;DNS;CDN;WebSocket vs SSE vs 轮询;CORS。
**常被问**:浏览器输入 URL 到页面发生了什么(经典综合题);HTTPS 怎么保证安全;TCP 怎么保证可靠。
**MindMarket 锚点**:Caddy 自动 TLS(Let's Encrypt);Cloudflare CDN + 隐藏源站;Copilot 用 **SSE** 流式(为什么不用 WebSocket:单向、HTTP 友好);CORS 配置;`{data,error,meta}` 信封里的状态码语义(401/422/429/503)。

## 1.4 并发与并行
**要懂**:并发 vs 并行;锁/信号量/CAS;竞态条件;原子性;async/await 事件循环;线程池 vs 进程池;幂等性 & 重试。
**常被问**:乐观锁 vs 悲观锁;如何实现一个线程安全的计数器/缓存。
**MindMarket 锚点**:进程内缓存的线程安全;`MetricsMiddleware` 在单 worker 下计数一致(多 worker 就要 Redis);Redis `SET NX` 做分布式锁。

---

# Part II — 后端工程(SDE 核心)

## 2.1 编程语言(以 Python 为主)
**要懂**:类型注解 + mypy;数据类/Pydantic;装饰器;生成器/迭代器;上下文管理器(`with`);async;打包/虚拟环境;常见坑(可变默认参数、闭包延迟绑定)。
**MLE 还要**:NumPy 向量化、pandas、广播。
**MindMarket 锚点**:Pydantic v2 在边界校验(`domain/models.py`);frozen dataclass 做引擎不可变输入;`@dataclass(frozen=True)` 的 `PortfolioScore`。

## 2.2 API 设计
**要懂**:REST 资源建模;HTTP 方法 & 幂等;状态码语义;版本化(`/v1/`);分页(cursor vs offset);统一响应信封;错误处理;**gRPC**(内部服务、protobuf、双向流) vs **GraphQL**(前端按需取数,解决 over/under-fetching)vs REST 的取舍;OpenAPI/契约。
**常被问**:REST vs gRPC vs GraphQL 怎么选;幂等怎么实现;分页为什么别用大 OFFSET。
**MindMarket 锚点**:`{data,error,meta:{request_id,elapsed_ms}}` 统一信封(`core/responses.py` 的 `ok()`);`/api/v1/` 版本化;前端 zod 校验信封;为什么选 REST 不选 gRPC(浏览器直连、简单)。

## 2.3 关系型数据库(SQL)
**要懂**:范式 vs 反范式;主键/外键/约束;**索引**(B-tree/Hash/GIN;复合索引最左前缀;覆盖索引);`EXPLAIN ANALYZE` 看执行计划;**事务 ACID**;**隔离级别**(读未提交/读已提交/可重复读/串行化)与幻读/脏读/不可重复读;锁(行锁/表锁、乐观/悲观);连接池(PgBouncer);N+1 问题;读写分离/读副本;分库分表。
**常被问**:索引原理 & 什么时候失效;隔离级别区别;如何排查慢查询;为什么用 B-tree。
**MindMarket 锚点**:Supabase Postgres;`portfolio_snapshots` 表;JSONB 列(`risk_metrics`/`data_quality`)+ 预留扩展位避免 migration;按 `user_id`/`created_at` 查询要建索引;RLS。

## 2.4 NoSQL & 数据模型选型
**要懂**:K-V(Redis)、文档(MongoDB)、列(Cassandra)、图(Neo4j)、时序(InfluxDB)、搜索(Elasticsearch);CAP 定理;何时用 NoSQL(高写入/弱关系/海量/灵活 schema)。
**常被问**:SQL vs NoSQL 怎么选;CAP 取舍;为什么投资组合用 Postgres 不用 Mongo(强关系 + 事务 + join)。

## 2.5 缓存(Redis 是重点)
**要懂**:
- 多层缓存:浏览器 → CDN → 进程内 LRU → Redis → DB(从近到远)。
- **Redis 的多角色**:缓存 / 限流 / 队列 broker / 分布式锁(`SET NX PX`)/ Pub-Sub / 排行榜(Sorted Set)/ 会话。
- **缓存三大问题**:穿透(查不存在 → 负缓存/布隆过滤器)、击穿(热 key 过期 → 加锁/逻辑过期)、雪崩(批量同时过期 → TTL 加随机抖动)。
- 模式:cache-aside、write-through、write-behind、**stale-while-revalidate**。
- 淘汰策略:LRU/LFU/TTL;持久化:RDB(快照)vs AOF(日志)。
- Redis vs Memcached(数据结构 + 持久化)vs 进程内(跨进程共享 vs 部署即丢)。
**常被问**:缓存一致性怎么保证;三大问题怎么解;Redis 为什么快(单线程 + 内存 + IO 多路复用 epoll)。
**MindMarket 锚点**:`services/cache.py` 的 `JsonCache`(Redis 优先,降级进程内 TTL+LRU);hash 做 key(不放密钥);负缓存(空结果短 TTL);stale-on-error;`fmp_provider` 的多域 TTL。

## 2.6 消息队列 & 异步处理
**要懂**:为什么要 MQ(削峰、解耦、异步、可靠);Kafka(高吞吐日志流)vs RabbitMQ(灵活路由)vs Redis(轻量);任务队列 Celery/RQ/Arq;at-least-once / exactly-once;死信队列;背压。
**常被问**:消息丢失/重复怎么处理;如何保证顺序;Kafka 为什么快。
**MindMarket 锚点**:目前同步调外部 API(**已知缺口**);规模上应该用 Arq(async 原生,配 FastAPI)+ Redis broker,把每日批量快照/embedding 生成异步化。

## 2.7 认证与授权
**要懂**:认证(你是谁)vs 授权(你能干嘛);Session vs **JWT**(无状态、可扩展、但难撤销);**JWKS**(非对称、公钥验签、密钥轮换);OAuth 2.0 / OIDC / **PKCE**(SPA 防授权码拦截);refresh token;**RBAC** vs **ABAC**;行级安全(RLS);密码哈希(bcrypt/argon2);CSRF/XSS。
**常被问**:JWT vs Session 取舍;JWT 怎么撤销;OAuth 流程;如何做多租户隔离。
**MindMarket 锚点**:Supabase Auth(邮箱 + Google PKCE);`PyJWKClient` 验 JWT(5s 超时防卡死);per-route `Depends(require_user)`;**RLS 把多租户隔离写进数据库**(`auth.uid()=user_id`);owner-gate(`require_owner`)。

## 2.8 系统设计(SDE 面试半壁江山)
**要懂**:
- 扩展性:垂直 vs 水平;无状态服务 + 负载均衡;**CAP / BASE / 最终一致性**;一致性哈希(分片)。
- 可靠性:冗余、故障转移、健康检查、优雅降级、熔断(circuit breaker)、重试 + 指数退避 + 抖动、超时。
- 性能:缓存、CDN、异步、批处理、连接池、数据库索引。
- 流控:**限流**(令牌桶/漏桶/固定/滑动窗口)、**幂等键**、背压。
- 数据:分库分表、读写分离、CQRS、事件溯源。
- 通用题:短链、发号器(Snowflake)、Feed 流、限流器、聊天系统、秒杀、网约车。
**常被问**:设计一个 X(见上);如何处理热点;如何保证高可用;一致性怎么权衡。
**MindMarket 锚点**:fail-soft 优雅降级(provider 挂了返回 None 不 500);`urllib3.Retry` 退避重试;JWKS 超时;限流缺口(靠 Cloudflare 边缘);单机 → 规模上 ALB + 多实例 + Redis 中心化。

## 2.9 可观测性(Observability 三支柱)
**要懂**:Logs(结构化 JSON)、Metrics(计数/直方图/Prometheus + Grafana)、Traces(分布式追踪 OpenTelemetry);SLI/SLO/SLA;告警;RED(Rate/Error/Duration)/USE 方法。
**MindMarket 锚点**:structlog;Sentry(错误);自制进程内 metrics 端点(`services/metrics.py`,纯 ASGI 中间件);PostHog(产品漏斗)。规模上 → Prometheus + OTel。

## 2.10 测试
**要懂**:测试金字塔(单元 > 集成 > E2E);TDD;mock/stub/fake;fixture;覆盖率(及其误区);property-based testing;契约测试。
**MindMarket 锚点**:pytest(后端 561 测试)、vitest(前端 259)、**Playwright E2E**(确定性 mock,无真实后端);fake Supabase client 做快照 round-trip;black/ruff/tsc/eslint 在 CI 把关。

## 2.11 安全
**要懂**:OWASP Top 10(注入、XSS、CSRF、越权、配置错误…);输入校验;最小权限;密钥管理;限流;HTTPS;依赖漏洞扫描。
**MindMarket 锚点**:Pydantic 拒 NaN/Inf/公式注入;RLS;Cloudflare WAF + 隐藏源站;密钥用 env 不入 git;owner 2FA(缺口)。

---

# Part III — DevOps / 云 / 部署

## 3.1 容器 & 编排
**要懂**:Docker(镜像分层、Dockerfile 优化、多阶段构建、`.dockerignore`);Compose(多容器);**Kubernetes**(Pod/Deployment/Service/Ingress、HPA 自动扩缩、何时该上 k8s)。
**常被问**:容器 vs 虚拟机;镜像怎么瘦身;k8s 核心对象;什么时候**不**该上 k8s。
**MindMarket 锚点**:`compose.split.yml`(前端/后端/caddy/legacy);**为什么不上 k8s**(单 t3.micro,杀鸡用牛刀);off-box 构建(OOM 教训)。

## 3.2 CI/CD
**要懂**:CI(自动测试/lint/构建)vs CD(自动部署);流水线设计;蓝绿/金丝雀/滚动发布;回滚;制品仓库(registry);**部署管线宁可多构建,不可静默漏部署**。
**MindMarket 锚点**:GitHub Actions(pytest/black/ruff/tsc/eslint/build/e2e);**GHCR pull-only**(CI 构建镜像 → EC2 只 pull,源于 OOM 事故);path 过滤从 allowlist 翻成 paths-ignore(静默不部署事故)。

## 3.3 反向代理 / 负载均衡
**要懂**:反向代理(Caddy/nginx)、负载均衡算法(轮询/最少连接/一致性哈希)、L4 vs L7、健康检查、TLS 终止、sticky session。
**MindMarket 锚点**:Caddy(自动 TLS,配置比 nginx 简单);路由 `/`→前端、`/api`→后端;**Caddyfile 语法错误导致崩溃循环**的事故(配置即代码,要 validate)。

## 3.4 云(以 AWS 为主)
**要懂**:EC2/ECS/Lambda;S3;RDS;VPC/子网/安全组;ELB/ALB;IAM(最小权限);CloudWatch;Auto Scaling;**IaC**(Terraform/CDK)。
**MindMarket 锚点**:EC2 + Elastic IP;安全组锁定到 Cloudflare IP 段;IAM 用户 `mindmarket-deploy`;systemd 开机自启(及重启回退事故 + 修复)。

---

# Part IV — 前端(全栈加分,SDE 友好)

**要懂**:HTML/CSS(Flexbox/Grid、响应式)、JS/TS、React(组件、hooks、虚拟 DOM、reconciliation、`useEffect` 陷阱)、状态管理(本地 state vs 服务端 state)、Next.js(SSR/SSG/CSR/ISR、App Router、server components)、构建打包(code-splitting)、Web 性能(Core Web Vitals)、可访问性、SEO。
**常被问**:SSR vs CSR vs SSG 区别与选型;React 重渲染优化;`useEffect` 依赖;状态管理选型。
**MindMarket 锚点**:Next.js 14 App Router(SEO/SSR,营销页要被索引);**React Query 管服务端 state**(不是 Redux);**zod** 编译期 + 运行时双校验;`queryKey` 含 `user.id` 隔离缓存;空骨架 prerender 事故(SSR + auth 状态)。

---

# Part V — MLE 专属

## 5.1 机器学习基础(必背)
**要懂**:
- 监督(分类/回归)/ 无监督(聚类/降维)/ 半监督 / 强化学习。
- **偏差-方差权衡**;**过拟合/欠拟合**及对策(正则化 L1/L2、dropout、early stopping、更多数据、交叉验证)。
- **训练/验证/测试集**;**数据泄露(leakage)**;K 折交叉验证。
- **评估指标**:分类(Accuracy/Precision/Recall/**F1**/ROC-**AUC**/PR-AUC/混淆矩阵;类别不平衡用 PR-AUC/F1 不用 accuracy);回归(MSE/RMSE/MAE/R²);排序(NDCG/MAP)。
- 损失函数;梯度下降(SGD/Adam);学习率。
**常被问**:precision vs recall 何时重要;AUC 含义;过拟合怎么办;为什么不平衡数据看 accuracy 没用;什么是数据泄露。
**MindMarket 锚点**:`data_quality` 置信度 = **calibration / 输入质量门控**;score 的确定性可复现 = 反黑盒;`ai_eval.py` = 输出评估。

## 5.2 经典算法(要能讲原理 + 取舍)
**要懂**:线性/逻辑回归、KNN、决策树、**随机森林 / GBDT(XGBoost/LightGBM)**(表格之王,为什么常胜深度学习)、SVM、朴素贝叶斯、K-Means、PCA/t-SNE/UMAP、协同过滤。
**常被问**:为什么 GBDT 在表格数据上强;随机森林 vs GBDT;K-Means 怎么选 K;PCA 原理;偏差方差怎么体现在树深度上。
**MindMarket 锚点**:`regime_detector` 的 **GMM**(高斯混合 + EM)是无监督聚类;ensemble + 信号加权 = 集成思想。

## 5.3 特征工程
**要懂**:缺失值处理、编码(one-hot/target/embedding)、标准化/归一化、分箱、特征交叉、时序特征(滞后/滚动/差分)、特征选择、**特征泄露**、训练-服务一致性(feature store)。
**MindMarket 锚点**:VaR/CVaR/因子/波动率 = 金融特征工程;`regime` 的滚动波动率/SMA 趋势/收益聚类 = 时序特征。

## 5.4 深度学习基础
**要懂**:神经网络(前向/反向传播、激活函数、初始化、BatchNorm、dropout);CNN(图像)、RNN/LSTM(序列)、**Transformer / Attention**(现代主流);优化器;过拟合对策;迁移学习/微调;框架 PyTorch(主流)/TensorFlow。
**常被问**:反向传播原理;梯度消失/爆炸;Attention 机制;为什么 Transformer 取代 RNN。
**MindMarket 锚点**:可加 LSTM/Temporal 做波动率预测(注意金融过拟合,要诚实)。

## 5.5 时间序列
**要懂**:平稳性、自相关、ARIMA、GARCH(波动率)、季节性、预测评估(walk-forward,**不能随机划分**)、leakage(用未来预测过去)。
**MindMarket 锚点**:波动率/regime 都是时序;回测要 walk-forward;`regime` 的 2y SPY。

## 5.6 ML 系统设计(MLE 面试核心,等价 SDE 的系统设计)
**框架(背下来)**:
1. **问题界定**:业务目标 → ML 目标;分类还是回归?在线还是批?延迟/吞吐要求?
2. **数据**:来源、规模、标签怎么来、隐私。
3. **特征**:工程 + feature store + 训练/服务一致性。
4. **模型**:基线(简单模型先行)→ 迭代;离线指标 vs 在线指标。
5. **评估**:离线(AUC…)+ 在线(**A/B 测试**)+ 业务指标。
6. **服务**:实时(低延迟)/ 批 / 流;模型版本化。
7. **监控**:数据漂移 / 概念漂移 / 模型性能衰减 / 反馈回路。
8. **再训练**:触发条件、pipeline、回滚。
**常被问**:设计一个推荐/欺诈检测/feed 排序系统;离线指标好但线上没用怎么办(分布偏移/leakage/反馈回路);怎么知道模型变坏了。
**MindMarket 锚点**:score_changes 的可解释分解 = 模型可解释性;data_quality 门控 = 数据质量监控的雏形。

## 5.7 MLOps 工具栈
**要懂**:
- 实验追踪:**MLflow** / Weights & Biases(可复现:params/metrics/artifacts)。
- 模型注册 & 版本化:MLflow Registry / DVC(数据 + 模型版本)。
- 数据校验:Great Expectations / Pydantic。
- 特征存储:Feast(在线/离线一致)。
- 编排:Airflow / Prefect / Dagster(定时 pipeline)。
- 漂移监控:Evidently / PSI(群体稳定性指数)。
- 分布式:Ray / Spark。
**常被问**:为什么要实验追踪;怎么保证训练-服务特征一致;怎么检测漂移。

## 5.8 模型服务与优化
**要懂**:实时(FastAPI/BentoML/Triton/TorchServe)vs 批 vs 流;**ONNX**(跨框架/加速);量化/剪枝/蒸馏(压缩);GPU vs CPU;batching;缓存;A/B + 影子部署(shadow)。
**MindMarket 锚点**:**模型服务层 = FastAPI,你已经会** —— 这是你的优势;LLM 的成本优化(Haiku/Sonnet 路由 + hash 缓存)就是 serving 优化思想。

## 5.9 LLM / 生成式 AI(2026 最热,你的强项)
**要懂**:
- Transformer/Attention;tokenization;上下文窗口;采样(temperature/top-p)。
- Prompt engineering;few-shot;chain-of-thought。
- **RAG**(检索增强):**embedding** → 向量库(**pgvector**/Pinecone/Qdrant/FAISS)→ 检索 top-k → 塞进 prompt;chunking;混合检索;rerank。
- 微调:全参 vs **LoRA/PEFT**(参数高效);何时微调 vs RAG vs prompt。
- **Agent / tool-use**;**MCP**(工具协议)。
- **LLM 评估**:幻觉检测、grounding、人评 vs 自动评、eval harness。
- **LLMOps**:prompt 版本化、guardrails、成本/延迟、可观测。
**常被问**:RAG 流程 & 为什么 chunk;微调 vs RAG 怎么选;怎么防幻觉;怎么评估 LLM 输出;向量库怎么选。
**MindMarket 锚点(你的王牌)**:**确定性 skeleton → LLM 只改写 + number-allowlist 校验**(防幻觉的架构级方案);意图路由器;模型路由;hash 缓存;MCP server;`ai_eval.py`;research 的 SEC/新闻可升级成 **pgvector RAG**(最自然的扩展)。

## 5.10 数据工程(MLE 邻接)
**要懂**:ETL/ELT;批 vs 流(Spark / Flink / Kafka);数据湖 vs 仓库;数据建模;数据质量;调度(Airflow)。

---

# Part VI — 系统设计面试通用模板(SDE & MLE 都用)

**45 分钟标准流程**:
1. **澄清需求(5min)**:功能性 + 非功能性(QPS、延迟、数据量、读写比、一致性要求)。**别急着画图。**
2. **容量估算(5min)**:QPS、存储、带宽(数量级即可)。
3. **API 设计(5min)**:核心接口签名。
4. **数据模型(5min)**:表/schema、选 SQL 还是 NoSQL。
5. **高层架构(10min)**:画框图(客户端 → LB → 服务 → 缓存 → DB/MQ)。
6. **深入细节(10min)**:挑 1–2 个点深挖(分片、缓存、限流、一致性)。
7. **瓶颈与取舍(5min)**:单点、热点、扩展、容灾;**主动说极限**。
**口诀**:需求 → 估算 → 接口 → 数据 → 架构 → 深挖 → 取舍。

**ML 系统设计**额外加:数据/特征/模型/离线评估/在线 A-B/服务/监控/再训练(见 5.6)。

---

# Part VII — 行为面试 / 简历 / 项目讲法

## 7.1 行为面试(BQ)
- 用 **STAR**(Situation/Task/Action/Result)。
- 备好故事:最难的 bug、冲突、失败、领导力、从 0 做的东西、做的取舍。
- **MindMarket 现成故事**:OOM 事故(定位→根因→系统性修复)、重启回退 + 潜伏 Caddyfile bug、静默不部署、500→70 健康分(从用户反馈到根因到护栏)。

## 7.2 简历(回顾前面给你的原则)
- 每行 = **用了什么技术 + 干了什么 + 量化结果**;动词开头;不用 senior 词(architected/led);不用弱词(helped/worked with)。
- 数字要真、能defend(~100× 向量化、13s→<1s 缓存、730+ 测试)。
- 删 coursework、删形容词 summary。

## 7.3 项目怎么讲(逐行能 defend)
每个技术点准备:① 解决什么问题 ② 替代方案及代价 ③ 失败模式/极限。**这是区分强弱候选人的关键。**

---

# Part VIII — 用 MindMarket 巩固每个知识点(锚点速查表)

| 知识点 | MindMarket 里去看 |
|---|---|
| 分层架构 / 依赖规则 | `libs/mindmarket_core/`(纯引擎)→ `backend/app/`(API)→ `frontend/`(UI) |
| 类型边界 / 校验 | `domain/models.py`(Pydantic)+ `frontend/src/lib/schemas.ts`(zod) |
| REST 信封 | `backend/app/core/responses.py`(`ok()`)+ `frontend/src/lib/api.ts`(`apiFetch`) |
| 认证 JWKS/RLS | `core/deps_auth.py` + `supabase/migrations/*`(RLS policy) |
| 缓存 / Redis | `backend/app/services/cache.py`(Redis + 进程内降级) |
| fail-soft / 降级 | `services/providers/fmp_provider.py`(`ProviderResult`) |
| 抗幻觉 LLM | `services/risk_explain.py` / `score_changes.py`(skeleton→LLM) |
| 量化 / VaR / MC | `risk_engine.py` + `libs/mindmarket_core/portfolio_scoring.py` |
| 模型鲁棒性 / calibration | `portfolio_scoring.py` 的 `data_quality` + 置信度收缩 |
| 集成模型 | `regime_detector.py`(GMM + vol + trend 加权) |
| 可观测性 | `services/metrics.py`(纯 ASGI 中间件)+ Sentry + PostHog |
| 测试金字塔 | `backend/tests/` + `frontend/src/**/*.test.tsx` + `e2e/`(Playwright) |
| CI/CD | `.github/workflows/`(build-images.yml pull-only) |
| 容器 / 代理 | `compose.split.yml` + `Caddyfile` |
| 生产事故 | `CLAUDE.md` 的 §2.8/§2.11(OOM)、§2.42(重启)、§2.44(500→70) |

---

# Part IX — 学习计划 & 资源

## 12 周计划(每周 ~15–20h,按你年底毕业倒推)
- **W1–4 DSA**:Blind 75 → NeetCode 150,按 tag。每天 2–3 题 + 复盘模式。
- **W5–6 基础**:OS / 网络 / 并发 高频题过一遍(对照 Part I)。
- **W7–8 系统设计**:套 Part VI 模板,练 8–10 个经典题;用 MindMarket 当案例库。
- **W9–10(分路)**:
  - **SDE**:数据库深入 + 分布式系统 + 更多系统设计。
  - **MLE**:Part V 全过 + 在项目里**加一条真 ML pipeline**(regime 有监督 / RAG)+ 复习 ML 数学。
- **W11 行为面试 + 简历**:STAR 故事打磨;模拟面试。
- **W12 冲刺**:模拟 + 查漏。

## 资源
- **DSA**:NeetCode(YouTube + 网站)、LeetCode、《算法(第4版)》。
- **系统设计**:《System Design Interview》(Alex Xu I/II)、ByteByteGo、Grokking the System Design。
- **ML**:吴恩达 ML/DL Specialization、《Hands-On ML》(Géron)、《Designing ML Systems》(Chip Huyen,**MLE 必读**)。
- **LLM**:《Building LLM Applications》、各家 cookbook、RAG/eval 博客。
- **后端**:FastAPI 官方文档(质量极高)、《Designing Data-Intensive Applications》(DDIA,**SDE 圣经**)。
- **行为**:STAR 模板 + 自己的 MindMarket 故事库。

---

## 附:面试前 24 小时速查(高频概念一句话)
- **索引**:加速查询的数据结构(B-tree),写慢一点换读快;失效场景:函数包列、最左前缀断、类型不匹配。
- **事务 ACID**:原子/一致/隔离/持久;隔离级别越高越安全越慢。
- **CAP**:网络分区时,一致性和可用性二选一(分布式)。
- **缓存三问题**:穿透(负缓存)、击穿(锁)、雪崩(TTL 抖动)。
- **JWT**:无状态、可扩展、难撤销;JWKS = 公钥验签。
- **幂等**:同一请求多次执行效果相同;写接口靠幂等键。
- **precision vs recall**:查准 vs 查全;不平衡数据看 F1/PR-AUC。
- **过拟合**:训练好测试差;正则化/更多数据/早停/交叉验证。
- **RAG**:embedding 检索证据 → 塞进 prompt → 生成;防 LLM 在证据外瞎编。
- **GBDT 表格之王**:树集成处理非线性 + 缺失 + 不需标准化,常胜 NN。
- **限流**:令牌桶(允许突发)/ 漏桶(平滑)/ 滑动窗口(精确)。
- **优雅降级**:依赖挂了返回兜底而非崩溃(fail-soft)。

---

> 维护建议:把这份文档当 checklist,学一块勾一块;每个 MindMarket 锚点都打开真实代码读一遍,确保你能逐行讲。面试不是比谁知道的工具多,是比谁能说清**为什么这么选、代价是什么、极限在哪**。
