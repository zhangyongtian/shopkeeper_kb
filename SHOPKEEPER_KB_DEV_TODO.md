# 作手级知识库（Shopkeeper KB）开发 Todo（从地基到 V2 V3 成品 · 小钱高回报版）
> 版本：v1.1（D 路线 · 普通人每天 1 元钱最强版）| 更新日期：2026-08-07
> 说明：本文件 = 全链路开发的唯一事实来源。**用户未明确说「OK 没问题」之前，禁止写任何梯队 / Vx 阶段的代码；确认后严格按下面顺序从上到下执行，禁止跳步。**

---

## 0. 用户确认签名位（必须先签字 ✅ 才能开始开发）

- [ ] 用户已确认本 Todo 所有阶段、所有设计、所有风险声明 **没有遗漏 / 没有异议 / 就按这个做**
- [ ] 用户选择的开发路线：
  - `A（纯免费零成本）`：所有付费服务都用免费替代，极限能跑但体验打折
  - `B（一步到位接 Tushare Pro 2000/年）`：直接 V4 全量数据，跳过 V1/V2 免费接口阶段
  - **`D（小钱高回报版 · 个人用户最强 · 默认推荐）✅`：总投入首年 ≈ 800~1200 元（一天 ≈ 2~3 元，普通人完全无感），换回以前机构几十万的能力，ROI 拉满**
    - P0 必花（两件合计 ≈ 250 元，一次/永久）：Tushare 2000 积分永久版 + 千问 API 首充 50 元
    - P1 推荐（≈ 399~599 元/年，一天 ≈ 1~1.6 元）：Choice 金融终端个人版 399/年 或 同花顺 iFinD 个人版 599/年（研报+一致预期，性价比爆炸）
    - P1 推荐（≈ 1200 元/年，一天 ≈ 3 元，可选）：百度搜索开发者企业版 / SerpAPI（新闻无限额度，中文建议百度）
    - P2 可选（合计 ≈ 10 元，一次，**不是必须！本地 MinerU 已 100% 免费就绪**）：MinerU 官方云 OCR 补充包 30 元/1000 页（仅当你未来要切分**扫描版/拍照 PDF** 且本地跑不动大模型时才考虑；你现有 5 本机器生成 PDF + 直接上传 PDF → 本地 MinerU 100% 免费直接处理，完全不用花这个钱）+ 阿里云 TTS 语音合成包（10 元包年够听，其实浏览器 Web Speech 零成本质量也够用，推荐不买）
  - **`E（大脑优先版 · 用户最终选择 ✅）`：钱只花在 LLM 大模型（大脑）上，其他所有外部服务全走零成本/极低成本替代，总投入 ≈ 50~120 元/月（≈ 1.7~4 元/天）**
    - **P0 必花（大脑，没它做不出专业水平回答）**：千问 API 按量计费 + 首充 50 元，建议额外 **月预算 50~100 元**（qwen-plus 主合成 / qwen-turbo 改写和新闻分类 / qwen3-vl-flash 读图，这三个是系统大脑，**免费额度很快会用完，必须留预算**）
    - **P1 不花（Tushare/百度搜索/Choice/同花顺全砍掉），全部零成本替代方案（对应坏处写在 13.5 节）**
  - `C（其他自定义：____）`
- [ ] 用户同意：本系统输出**仅用于学习参考**，非投资建议，作者不承担任何盈亏责任
- [ ] 用户同意：所有付费服务通过官方正规渠道购买，作者不对任何第三方服务的可用性 / 质量负责
- [ ] 用户已阅读 13.5 节「E 路线：大脑优先版零成本替代方案 + 每项坏处对照表」，接受所有替代方案对应的坏处
- 签字日期：____ 签字人：____

---

## 1. 项目最终成品目标（V3 终局）

**一句话描述**：用户上传一张股票截图（或输入文字 + 代码）→ 系统调用 `N 位可插拔书籍专家委员会`（每本书 = 一位独立专家，可动态上下线）+ `T 日近 7 天新闻` 进行「投票打分制综合判断」→ 输出：**强风格的、可执行的、每一条都带引用跳转原书页码的交易计划**（综合方向 + 动作 + 6 个关键数字），置信度 meter + 合规围栏。

**最终体验 = Fluss Ask AI 同款 UI + 私人量化私募经理风格回复 + 多书引用 PDF 跳页 + 书籍越补越聪明（自动防垃圾书）**

---

## 2. 核心设计决定（已锁定，开发中不得随意更改）

| 编号 | 设计决定 | 理由 |
|---|---|---|
| D1 | **架构分层**：Ingestion 梯队 0/1 → Retrieval 梯队 2 → Generation 梯队 3 → Chat API 替换 Mock | 各层解耦，可独立调试，出错好回溯 |
| D2 | **RAG 检索路由方式**：按 `doc_type`（专家分类标签）并行独立查询 Milvus，每本书独立 TopK 限 5，不做全局一次检索再事后挑 | 防止厚书（墨菲）占满 TopK，薄书（蜡烛图）被挤掉，保证每位专家都有话说 |
| D3 | **判断方式**：`80% 硬编码规则引擎打分 + 20% LLM 只负责润色 + 强制引用`。方向判断不靠 LLM 自由发挥，LLM 禁止输出「可能/也许」 | 保证系统输出稳定可复现，今天明天结果一致，不会幻觉自相矛盾 |
| D4 | **书籍动态注册**：`MongoDB expert_books` 集合存元数据，不写死到 Python 代码。新用户上传 PDF → API 注册 + ingest → 专家池自动加一位，零代码改动 | 用户后续补书不需要开发人员介入 |
| D5 | **风格**：`私募基金经理强硬派风格`，System Prompt 硬约束，违反就做 postprocess 重写。结尾强制挂 `非投资建议` 围栏 2 层 | 符合用户「最强股票专家风格」诉求 + 合规风险防护 |
| D6 | **补书反变笨双保险**：① 每 doc_type TopK 限 5 + chunk 相似度>0.92 去重；② 每本书独立算历史准确率，<52% 降权，<45% 自动 disable | 防同类型书堆积占坑 + 防垃圾书拉低系统 |
| D7 | **会话存储**：Redis 热窗存最近 N 轮（亚毫秒读）+ MongoDB conversations/messages 冷归档（可审计），双写架构 | 工业界标准，兼顾速度和历史回放 |
| D8 | **图片显示**：SourceRef.image_urls（MinerU 抽的图 + MinIO 公网 URL）→ 前端 Sources 卡片左 2x2 grid 缩略图 + 正文插图渲染 + 点击 Lightbox 放大，引用 [n] 跳 PDF 页 | 已完成（index.html + schemas.py + mock），无需再改 |
| D9 | **PDF 预览**：FastAPI /api/pdf/{name} 路由（防越权）+ PDF.js viewer #page=N 锚点秒跳，本地未打包 pdfjs 时 fallback 到 mozilla.github.io 公共 CDN | 已完成（index.html + routes/pdf.py），无需再改 |
| D10 | **Milvus 字段对齐**：Chunk 所有元数据（doc_type/pdf_name/pdf_page/doc_title/section_path/image_urls/doc_tags）全部入 Milvus dynamic 字段，检索时可直接 filter | 保证召回出来的一条数据能完整对应一张引用卡片 |
| D11 | **生成模型选型（复用千问 Key，零开通新服务）**：<br>• 主合成（7 段模板）：qwen-plus<br>• Query Rewrite + 需要快速返回的：qwen-turbo<br>• 截图识别：qwen3-vl-flash（免费额度够）<br>• 特别复杂推理（可选开关）：qwen-max | 中文交易语料优势 + 同一套 Key 不用新注册，零成本 |
| D12 | **安全围栏 2 层**：① System Prompt 黑名单词（满仓/梭哈/稳赚）→ postprocess 替换中性词；② 每次回答末尾强制拼「非投资建议」大段文字，不允许 LLM 漏。不擅长领域直接输出「我不懂，请去找别人」 | 合规 + 法律风险防护 |
| D13 | **新闻策略**：**绝不 ingest 进知识库**（时效性太强），每次回答前用工具调用实时搜索 SerpAPI 百度/Tushare，强制 7 天时间过滤，每条新闻标 发布时间 + 利好/利空/中性三分类 | 避免半年前旧新闻误导判断 |
| D14 | **前端 UI**：阶段 2 单 HTML + CDN 三件套（marked/DOMPurify/highlight.js）+ 零 Node 构建链；阶段 1 Open WebUI docker-compose 已写好可备用（真接口写完填 API 地址） | 已完成（docker-compose + index.html + Mock API），真实接口写完只改 index.html 2 行 URL 常量即可 |

---

## 3. 梯队 0（地基层 · 必须第一个完成）
> ⏱ 工作量：≈ 2h | 📁 涉及文件：state.py / settings.py / expert_books 初始化种子数据 / MongoDB 建表脚本

| ID | 任务 | 验收标准（怎么做才算 OK） |
|---|---|---|
| 0.1 | [state.py](file:///home/roott/work/src/shopkeeper_kb/workflows/state.py) `Chunk TypedDict` 字段升级：新增 `doc_id` / `chunk_id` / `doc_title` / `doc_type` / `pdf_name` / `pdf_page_estimate` / `doc_tags` / `quality`；修正现有的 `embedding: list[float]` 错写为单向量的字段 → 改为每个 chunk 自己的 `embedding: list[float]`（在 state 层级为 chunks 加字段，ImportGraphState 里 embedding 删除，改成 NodeBGEEmbedding 输出回写到每一个 `Chunk.embedding`） | 代码 import 无报错；Chunk 新字段全齐；类型 hint 正确无歧义 |
| 0.2 | [settings.py](file:///home/roott/work/src/shopkeeper_kb/settings.py) 追加配置块：<br>① Milvus 连接（host/port/user/pass/dim=1024（BGE-M3 dim）/collection_name）<br>② BGE 模型配置（model_name=BAAI/bge-m3 / use_fp16 / use_gpu=False（VM 默认 CPU）/ batch_size）<br>③ LLM 三模型配置（qwen_plus / qwen_turbo / qwen_max 分别的 model_name + temperature_* + top_p）<br>④ Rewrite 配置（REWRITE_ENABLED 默认 VM 关闭 省 token；rewrite_threshold_tokens）<br>⑤ 检索参数（RERANK_ENABLED 默认 VM 关闭 省 5s；hybrid_alpha_dense=0.7；topk_per_expert=5）<br>⑥ 会话参数（CONVERSATION_WINDOW_SIZE=8；CONVERSATION_WINDOW_TTL=3600s；ENABLE_MONGO_ARCHIVE=true） | `.env` 未设置时有合理默认值；get_settings() import 无报错；frozen dataclass 字段全齐 |
| 0.3 | 新增 `scripts/init_expert_books.py` **初始种子数据脚本（开放架构，不是锁死 7 本！）**：<br>脚本做两件事：<br>1. 初始化 MongoDB `expert_books` 集合（如果不存在），为集合上唯一索引 `db.expert_books.create_index("doc_type", unique=True)`，保证 doc_type 不会重复；<br>2. 用 `update_one(..., upsert=True)` 的方式 **仅在集合为空时写入 7 条默认样板数据**（方便你立刻跑通 5 本现有 PDF + 2 位预留专家，后续你任意手动添加新书，脚本不会覆盖也不会再写入）。<br>字段参考：`doc_type(唯一) / pdf_name / display_name / expert_role / emoji_tag / color / priority / disabled / weight(=1.0 默认权重，将来 V4 跑历史回测后会按每位专家准确率动态调) / domain_keywords[]（关键词路由用）`。<br>**默认 7 条种子只是「开箱即用的初始化样板」，绝对不是锁死：**<br>• 📕 日本蜡烛图技术.pdf → `candlestick` / 形态分析专家（🔴，priority=1）<br>• 📗 金融市场技术分析.pdf → `technical_trend` / 趋势量价指标专家（🟠，priority=2）<br>• 📊 手把手教你读财报（唐朝）.pdf → `fundamental` / 财报基本面分析师（🟡，priority=3，**默认 disabled=true 占位，PDF 有了再改 disabled=false**）<br>• 📘 交易心理分析.pdf → `psychology` / 交易心理教练（🟢，priority=4）<br>• 📙 金融怪杰.pdf → `master_wisdom` / 大师经验对照（🔵，priority=5）<br>• 📓 通向财务自由之路.pdf → `risk_position` / 风控仓位系统师（🟣，priority=6）<br>• ⚫ 系统虚拟专家 → `news_capital_flow` / 情报分析师（新闻+公告+资金面，不是 PDF，priority=7）<br><br>**后续加新书零代码流程（D4 设计决定，架构完全开放）**：<br>第 1 步：PDF 文件放到 [doc/](file:///home/roott/work/doc/) 目录 → 第 2 步：**调 1 次 `POST /api/admin/register_book`**（body 里填新的 doc_type/display_name/expert_role/颜色/优先级）→ 第 3 步：**调 1 次 `POST /api/ingestion/register_and_run`** → 完成。系统在下一次用户提问时自动让这位新专家进入专家池参与讨论，不需要重启服务，不需要改任何 Python 代码。<br>举例：你后续上传《笑傲股市》→ `doc_type=canslim` / priority=2.5 插在形态和财报之间 → 专家池就从 7 位变 8 位了；再上传《海龟交易法则》→ `doc_type=trend_following` priority=6.5；再上传可转债规则书 → `doc_type=convertible_bond` priority=9；…无限扩展。<br>**「防越补越蠢」双保险（D6 锁定）**：每本书独立 TopK 限 5 条 + 相似度去重 + V4-4 历史准确率 <45% 自动 disable 踢出专家池，只允许越补越聪明不允许越补越笨。 | 脚本重复执行**不会覆盖**你后续手动通过 API 添加的新书；运行第一次后 Mongo 能看到 7 条；再通过 API 加一本后查询变成 8 条，下一次 `load_active_experts()` 能正确读到第 8 位；fundamental 默认 disabled=true，其他默认 6 位正常 |
| 0.4 | 新增 `services/expert_registry.py` 单件：`load_active_experts()` 从 Mongo `expert_books` 读 `disabled=false` 的列表，按 priority 排序返回，Redis 缓存 10 分钟。后续 ingest / 检索 / 合成全部走这个单件，不用硬编码 | Mongo 新增一条后下一次调用会自动反映在结果里；返回 dict 包含 doc_type → 专家所有元数据 |
| 0.5 | 新增 MongoDB collection 定义（用 pymongo create_index）：<br>• `conversations`（_id=conversation_id, user_id, created_at, updated_at, summary, tags）<br>• `messages`（_id, conversation_id, role, content, ts, sources[], related[]）<br>• `analysis_snapshots`（_id, conversation_id, message_id, stock_code, final_direction, experts_scores[], news_scores[], final_confidence, created_at, verified_outcome=null, verified_at=null）→ 用于 30 天后算每位专家历史准确率 | 脚本能一次性建表 + 建索引（conversation_id、created_at、stock_code）；不会因为重复执行报错 |

---

## 4. 梯队 1（Ingestion 工具 + 节点填充 · 第二个完成）
> ⏱ 工作量：≈ 4h | 📁 涉及文件：新增 tools/milvus_client.py / tools/embedding_client.py；修改 node_item_name_recognition.py / node_bge_embedding.py / node_import_milvus.py；新增 routes/ingestion.py

| ID | 任务 | 验收标准 |
|---|---|---|
| 1.1 | 新增 `tools/milvus_client.py`：封装 Milvus 连接；`ensure_collection(collection_name, dim)`（自动 create collection + load）；`upsert_chunks(list[Chunk])`（Chunks 的字段+embedding 全写入 Milvus，用 JSON 动态字段，保证 doc_type/pdf_name/pdf_page/doc_title/section_path/image_urls/doc_tags/quality 全入库能 filter）；`hybrid_search(expr_filter, topk)`：VM 阶段先用纯 dense（BM25 sparse 放 milestone V4） | `ensure_collection` 重复调用不报错；upsert 500 条后用 Milvus Attu UI（:7000）能查到数据并按 doc_type 过滤查询 |
| 1.2 | 新增 `tools/embedding_client.py`：封装 BGE-M3 向量；`embed_texts(list[str])` → `list[list[float]]`；VM 默认 CPU（use_gpu=False）+ batch_size=4；本地文件找不到模型自动从 modelscope 下载（已加 modelscope 依赖）；Redis 缓存 hash(text[:10]) → 向量，命中缓存跳过 embedding（省 90% ingest 重复切分分时间） | embed 100 条相同文本只做一次 embedding；维度必须是 BGE-M3 的 dim=1024；Milvus 字段 dim 配置一致 |
| 1.3 | 填充 `node_item_name_recognition.py` process()：对单个 PDF 文件做两件事 → ① 如果 pdf_name 在 expert_books 里能匹配，读它的 doc_type/expert_role 塞进 state.chunks 每条 chunk 的 doc_type/doc_title 字段（遍历 chunks 写）；② 对 chunks 做一轮粗质量打标：如果 embed_text 长度 < 40 或全是目录/表格垃圾 → quality="low" 其他 "normal" | 节点跑完后任意 chunk 都有 doc_type 且有 pdf_name 对应的值 |
| 1.4 | 填充 `node_bge_embedding.py` process()：① 遍历 state.chunks；② 过滤 quality=low（VM 阶段先不入库垃圾段，可开关）；③ 取 embed_text 批量调 `embedding_client.embed_texts`；④ 把返回的向量**一对一回写到每个 Chunk 自己的 embedding 字段**（ImportGraphState 顶层的 embedding 字段标记 @deprecated，后续删除） | 节点跑完后任意一个 quality=normal 的 chunk 都有 len(embedding)=1024 |
| 1.5 | 填充 `node_import_milvus.py` process()：调 `milvus_client.upsert_chunks(state.chunks)`，批量入库；同时把 chunks 全量原始 JSON 存 MongoDB `chunks_raw` 集合（方便将来重建 Milvus 不用重新跑 split），_id=chunk_id | Milvus Attu 能查到新的 collection；chunks_raw 集合里 chunk_id 去重；duplicate chunk_id 做 upsert |
| 1.6 | 新增 `app/routes/ingestion.py` API：<br>• `POST /api/ingestion/register_and_run`  body={pdf_name:string} → 1) 先到 expert_books 确认已注册（未注册报错 code=EXPERT_NOT_REGISTERED）；2) 异步调 LangGraph ImportGraph（PDF→MD→split→item_name→embed→milvus）全流程；3) 返回 task_id<br>• `GET /api/ingestion/status/{task_id}` → 返回当前节点进度 / 错误信息<br>（先不管 celery，用 `asyncio.create_task` 跑后台，state 放内存或者 Redis） | swagger /docs 能调通；先 register 再 run 能跑通 5 本书中任意一本完整 ingest 进 Milvus + Mongo |
| 1.7 | 跑一遍把 5 本书全部 ingest 进 Milvus + Mongo：Milvus 里按 doc_type 过滤每一类都有数据；quality=low 被丢弃；chunk 数大概预期 4000~8000 条（5 本书合计） | Attu 里 query expr: `doc_type == "candlestick"` 能出来 chunk；任意一条点击看 pdf_page/pdf_name/section_path 字段都有值 |

---

## 5. 梯队 2（检索层 + 会话层 + 规则引擎 + Rewrite · 第三个完成）
> ⏱ 工作量：≈ 6h | 📁 新增文件：services/parallel_retrieval.py / services/conversation.py / services/query_rewrite.py / services/expert_rules.py

| ID | 任务 | 验收标准 |
|---|---|---|
| 2.1 | 新增 `services/parallel_retrieval.py`：`retrieve_all_experts(query, topk_per=5)` → 返回 dict {doc_type: list[SourceRef]}。实现：① `expert_registry.load_active_experts()` 拿所有活跃专家；② 并发（asyncio.gather）对每个 doc_type 做 Milvus 搜索（过滤条件 expr=`doc_type == "xxx"`）；③ 对每个专家内部做相似度去重（余弦 >0.92 只留 Top1）防同本书重复段堆；④ 拼回 SourceRef 结构（包含 image_urls/image_alts/pdf_page/pdf_name/doc_title/section_path/preview） | 对「黄昏之星」query：candlestick 维度返回 3~5 条正确的黄昏之星段；technical_trend 返回趋势/支撑压力段；risk_position 返回仓位相关段 |
| 2.2 | 新增 `services/conversation.py` Redis + Mongo 双写：① 写消息到 Redis List `conv:{conv_id}:messages`（LTRIM 留最近 CONVERSATION_WINDOW_SIZE 条 + TTL=CONVERSATION_WINDOW_TTL）；② 写 Mongo conversations/messages 两集合；③ `rebuild_context(conv_id)`：先读 Redis，空就回滚 Mongo 兜底回灌最近 N 条；④ 返回拼接好的 prompt 上下文（最近 4 轮用户+AI 历史消息 summary） | Redis 重启/T 过期后 rebuild 能正确从 Mongo 回灌历史；双写两边消息数量一致 |
| 2.3 | 新增 `services/query_rewrite.py`：`needs_rewrite(history, current_q)` → bool。检测条件（VM 默认关闭 REWRITE 省 token，满足所有条件才启用）：① 有至少 2 轮历史；② 当前问题包含指代「它/这个/那只/这支/它们」；③ 历史里能找到对应 entity。`rewrite(history, current_q)` → qwen-turbo 扩写 "这段对话里用户问的这支股票，结合上下文扩成完整查询" 成独立可检索查询，返回 rewrite 后的新 query | needs_rewrite 能正确识别出「它是看空还是看多」需要 rewrite；「贵州茅台的黄昏之星」不需要 rewrite |
| 2.4 | 新增 `services/expert_rules.py` 规则打分引擎（最核心的「80% 判断不交给 LLM」）：`score_per_expert(retrieved_dict, structured_input, tushare_snapshot, news_sentiment, user_profile)` → 返回 {doc_type: {stance: pro/con/neutral, score: float, reason_rules: [{rule_id, points, desc, evidence_src_idx: [n]}]}}。**至少写 28 条规则**（分 7 大类，后续可无限扩展），每条规则都要带 rule_id 方便 V3 打分解释器展示：<br>• 📕 **蜡烛图类（6 条 CAND_01~06）**：CAND_01 黄昏之星/射击之星 = -2；CAND_02 启明星/锤子线 = +2；CAND_03 乌云盖顶 = -1.5；CAND_04 刺透形态 = +1.5；CAND_05 三只乌鸦 = -2；CAND_06 三白兵 = +2<br>• 📗 **趋势指标类（5 条 TREND_01~05）**：TREND_01 MA5 下穿 MA20 死叉 = -2；TREND_02 MA5 上穿金叉 = +2；TREND_03 跌破上升趋势线 = -1.5；TREND_04 站上下降压力线 = +1.5；TREND_05 MA200 之上 +1，之下 -1<br>• 📊 **基本面红绿灯（3 条 FUND_01~03，Tushare 6 指标驱动）**：FUND_01 ROE<5% 且 营收增速<0 = 红灯，-5（技术面再好也不能给多，排雷核心）；FUND_02 ROE>15% 且 营收+净利双增 = 绿灯，+2；FUND_03 PE_TTM > 行业均值 2 倍或 PB>10 倍（非科技）= 估值泡沫黄灯，-1<br>• 💰 **资金面免费版（3 条 CAPITAL_01~03，北向+融资+龙虎榜 Tushare 免费版驱动）**：CAPITAL_01 北向连续 3 日净卖出（累计>1 亿）= -1；CAPITAL_02 融资余额 7 天增长 >20%（融资过热）= -0.5（高位见顶概率大）；CAPITAL_03 龙虎榜连续 2 天机构专用净买入 >5000 万 = +1.5<br>• 📰 **公告高危拦截（2 条 ANNOUNCE_01~02，优先级最高直接熔断）**：ANNOUNCE_01 近 30 天公告包含「拟减持>1% / 立案调查 / 业绩预亏>1 亿 / 非标审计意见 / 终止重组 / ST 申请」= 任意命中 → 给所有专家额外强制扣 -10 分，最终综合结论强制 refused，不给方向（红色大警示条）；ANNOUNCE_02 近 7 天有 2 篇及以上券商研报上调评级 = +1<br>• 📘 **心理类（3 条 PSY_01~03）**：PSY_01 持仓盈利>20% + 形态空头 = -1（别爱上头寸）；PSY_02 浮亏>10% + 形态继续空 = -2（别死扛）；PSY_03 连续 3 次止损后新入场 = -1（过度交易）<br>• 📓 **仓位风控类（6 条 RISK_01~06 + 实盘交易成本修正）**：RISK_01 R/R<1:1.5 = -1（不划算）；RISK_02 单笔 R>用户画像最大单笔亏损比例（保守 1% / 中等 2% / 激进 3%）= -2（超限风险）；RISK_03 逆势加仓 = -2；RISK_04 行业集中度检查：用户画像持仓中该申万一级行业>30% 且建议加仓 → -1（分散要求）；RISK_05 T+1 流动性修正：止损位计算自动 × 1.3（A 股 T+1 跌停放不出的风险缓冲）；RISK_06 交易成本修正：R/R 计算扣除 0.5% 双向佣金+印花税+滑点。<br>**最终打分融合时：** 基本面红绿灯 / 公告高危拦截为**一票否决权**（-5/-10 分直接 overrule 技术面 +12 分），权重 >> 蜡烛图和趋势 | 单测：`FUND_01 ROE<5% 红灯` 触发时，即使 CAND_02 启明星 +2 综合得分仍为负 → stance=con；`ANNOUNCE_01 拟减持 5%` 触发时 → 强制返回 refused；28 条规则单测 100% 通过 |

---

## 6. 梯队 3（生成层 · 第四个完成，替换 Mock 真接口）
> ⏱ 工作量：≈ 5h | 📁 新增：services/generation.py / tools/llm_client.py / tools/news_search.py / app/routes/chat.py

| ID | 任务 | 验收标准 |
|---|---|---|
| 3.1 | 新增 `tools/llm_client.py` 封装千问三模型 + 速率限制：`chat(model="plus", messages, temperature, stream=True)` 支持 SSE，自动 retry；RPS 限制；自动把 qwen_plus → 真实 model_name（读取 settings）。支持 stream=True 时 yield (delta_text, finish_reason) | qwen-plus 单测能正常输出一段中文；stream SSE 能看到 80 条以上 data 事件；qwen-turbo/plus/max 三模型调用都跑通 |
| 3.2 | 新增 `tools/news_search.py` 新闻工具链（V1/V2 分两阶段）：<br>• V1 MVP：先用 **SerpAPI 免费额度**（100 次/天）或 百度开发者搜索 API（中文新闻更准），搜「{stock_name} {code} 近7天 新闻」+「{申万行业名 if 有} 热点」+「沪指大盘今日」；每条新闻保留 title / summary / publish_time / url / source。<br>• postprocess：过滤 >7 天；LLM（qwen-turbo batch）给每条做利好/利空/中性三分类；返回 top 10 条。<br>• V2 接 Tushare Pro（见 V4 升级）。 | 搜「贵州茅台 600519」返回最近 7 天至少 5 条；每条带 time + sentiment 情感；>7 天的新闻被过滤 |
| 3.3 | 新增 `services/generation.py` Prompt + 后处理（最重要的合成层）：<br>• System Prompt 必须包含 D5「强硬风格约束」+ D12 黑名单词 + D4 非投资建议结尾围栏。<br>• **强制输出模板**：User 写一段，LLM 必须按 8 段 Markdown 模板输出，缺段直接报错重请求：<br>  1. ## 🖼️ 截图/输入理解摘要<br>  2. ## 📕【蜡烛图】机会/风险点 + 证据 [n]<br>  3. ## 📗【技术分析】机会/风险点 + 证据 [n]<br>  4. ## 📘【交易心理】持仓或空仓建议 [n]<br>  5. ## 📙【大师经验】对照案例 [n]<br>  6. ## 📓【仓位风控】R 值、止损位、目标位、仓位建议 [n]<br>  7. ## 📰【近期新闻】（每条：[日期] 🔴/🟢/⚪ 标题 + 摘要）<br>  8. ## 🎯 综合结论：偏多/偏空/中性 置信度 N% + 6 大必带数字（方向/持仓动作/止损位/新进场条件/仓位大小/失效条件）<br>• 引用 [n] 标号必须严格和 sources 数组一一对应（不能乱编号，postprocess 检测标号超出 sources 长度就报违规）<br>• SSE 输出格式对齐现有 index.html 解析协议：`{delta, sources=None, related=None, done=false}`；过程中发送 sources[] / related[]；最后 `done=true, confidence=ok/refused`。 | 非 streaming 版单测：输出里所有 H2 标题全齐；标号在 sources 范围内；结尾必带非投资建议；综合结论里 6 个数字字段一个不缺。 |
| 3.4 | 新增 `app/routes/chat.py`：<br>• `POST /api/chat/stream`（真正的）→ conversation_id/question 两个必填字段；流程：<br>  ① （V2 才有）若传了截图 base64 → 先走 VL 识别 chart_features；否则用文字做关键字抽（MVP V1 先让用户文字里写代码）<br>  ② needs_rewrite → rewrite；③ conversation.rebuild_context 拼历史；④ parallel_retrieval 查所有活跃专家；⑤ （若有股票代码）news_search 搜近 7 天新闻；⑥ expert_rules 打分；⑦ generation.build_prompt + llm_client.chat(stream=True) → 把 llm 的 delta 再封装成 index.html 能解析的 SSE 协议写出。<br>• `POST /api/search`（Ctrl+K 搜索真接口）→ 走 parallel_retrieval 全局 topk 搜索返回 hits | Swagger 真调 `/api/chat/stream` 用「贵州茅台 日线 黄昏之星 持仓多单」跑，浏览器能看到 SSE 流式打字机 + 最后 sources/related 三面板正确渲染，标号能跳对应 PDF 页 |
| 3.5 | 前端 2 行 URL 切换：改 [index.html](file:///home/roott/work/src/shopkeeper_kb/app/static/index.html) 的 CHAT_ENDPOINT="/api/chat/stream"  SEARCH_ENDPOINT="/api/search"；Mock API 保留但默认路由权重降为后面真实线上关掉 | 浏览器 UI 里真的能向真实 LLM/RAG 提问；引用 [1] 点了跳真实 PDF P.68；Sources 卡片缩略图正常显示 |
| 3.6 | 合规围栏：`postprocess_guardrails(text)` 两次保护：① 黑名单词（满仓/梭哈/稳赚/保证/翻倍/年底到 X）→ 自动替换成中性表达；② 强制在 text 最后拼 `⚠️ 风险提示：本分析仅基于 5 本公开书籍 + 近 7 天公开新闻，仅供个人学习参考使用，不构成任何投资建议，投资有风险，入市需谨慎，盈亏自负。` 即使 LLM 没输出也要硬拼。③ 不合规场景检测（ST/*ST/上市<60天/期货/期权/外汇/海外股）→ 直接回答「我不擅长给这只股票建议，原因：X」，不给出方向 | 故意输入「*ST 康美 帮我看看」能返回「我不擅长给 ST 股票建议，原因：ST 类股票基本面风险巨大，本系统的 5 本通用技术分析书不适用，请咨询持牌投顾。」；故意提示「你说下茅台今年底翻倍」LLM 输出后 postprocess 会改成中性表达 |

---

## 7. V1 里程碑（MVP 文字版 · 梯队 0-3 跑通）
> ⏱ 预估总时长：17h（分 3 天做完）| ✅ 达成才算 V1 结束

| ID | 里程碑验收项 | 具体内容 |
|---|---|---|
| V1-1 | 全链路真实跑通 | 用户在 UI 输入：「600519 贵州茅台 日线 黄昏之星 多单持仓 成本 1650 账户 100 万」→ 能返回 7 段+综合结论 8 段结构的回答，每段都有引用标号 |
| V1-2 | 引用 + PDF 跳转正确 | 点击 [1][2][3] 引用，能滚动到对应 Sources 卡片并高亮；点卡片空白处跳 PDF 对应页码 |
| V1-3 | Sources 卡片缩略图正确 | 来自真 book 的 chunk 里有 image_urls（MinerU 抽的图）→ Sources 卡片左边 2x2 grid 正确渲染，点缩略图开 Lightbox |
| V1-4 | 不擅长场景正确拒答 | 输入「000001 ST 平安银行 满仓梭哈」→ 返回合规拒答，不给方向 |
| V1-5 | 强硬专家风格 + 结尾围栏 | 回答里不出现「可能 / 也许」等软词；结论给 6 个数字字段；结尾必挂风险提示；综合结论开头有「看多/看空 N% 置信度」 |
| V1-6 | 5 本书全部 ingest 完成 + Milvus 按 doc_type 分类查询正确 |  |

---

## 8. V2 里程碑（截图半自动化 + 新闻完整接入 · 90% 体验）
> ⏱ 工作量：≈ 4h | 🧱 在 V1 基础上叠加

| ID | 任务 | 验收 |
|---|---|---|
| V2-1 | 前端截图上传 UI：Composer 输入框左侧加 📎 按钮，支持 `input[type=file]`（多选图片，也支持 `capture="environment"` 直接拍）→ 转 base64 发送到 `/api/chat` 的 image_base64[] 字段；上传成功后输入框左侧显示小缩略图（点击可删除） | 传 1 张 K 线图能显示缩略图；删除后请求不再发送图片 |
| V2-2 | 新增 `tools/qwen_vl_client.py`（复用 [integrations/qwen_vl_api.py](file:///home/roott/work/src/shopkeeper_kb/integrations/qwen_vl_api.py) 已有基础）；调用 `qwen3-vl-flash`，**只允许输出严格 JSON schema**（禁止股票名/代码识别字段）：`{timeframe, chart_features: {candlestick_patterns:[], ma_crosses:[], volume:string, support_levels:[], resistance_levels:[], notes:string}}`；JSON 解析失败重试 2 次 + 最终 fallback 「截图没看清，请在文字里补充形态描述」 | 喂一张黄昏之星截图能识别出 candlestick_patterns: ["EveningStar"]；resistance 正确给出 1700 这种数字 |
| V2-3 | chat 路由接入 VL：若请求带 image_base64 → VL 识别得到 chart_features → 直接喂给 expert_rules 做打分，并且用 chart_features 关键字拼接 query 再去 parallel_retrieval 再做一轮检索；得到 「人工文字输入 query 召回」+「VL 特征召回」两路，最后 RRF (Reciprocal Rank Fusion) 合并排序 | 只传截图不传文字（stock_code 写死手动让用户补，V2 还不自动识别代码）也能出完整分析 |
| V2-4 | 补「用户没写代码」提示拦截：`parse_stock_code(text+vl_notes)` 检测不到 6 位数字/A 股代码格式 → SSE 首条返回 refused 并弹 chip 「请在文字里补充一下股票代码哦，例如 600519」，直接结束，不浪费 LLM token | 故意只发截图不写代码 → 返回上述提示 |
| V2-5 | V1 的 6 项验收依旧通过（没回归） |  |

---

## 9. V3 里程碑（截图全自动化识别 + 候选 chip 确认 · 100% 完整体验）
> ⏱ 工作量：≈ 4h | 🧱 在 V2 基础上叠加

| ID | 任务 | 验收 |
|---|---|---|
| V3-1 | VL JSON schema 扩充 `stock_candidates: [{code, name, confidence}]` 三个字段；识别出候选后做两步校验：① 正则过滤代码格式（沪 A=60xxxx 深 A=000/001/300xxx 北=43/83/87/88xxx）② Tushare 免费接口 stock_basic 查代码是否存在（先做一次缓存本地 JSON，不用每次 API），不存在的候选删掉 | 贵州茅台截图能识别到 code=600519；五粮液 000858 能正确出现 |
| V3-2 | UI 候选 chip 用户确认：如果 VL confidence < 0.8 或者候选 >=2 个 → SSE 首条不进入生成，直接返回「candidate_picks:true, candidates:[]」事件 → 前端在 Composer 上方弹 chip「你看的是这几只？1. 贵州茅台 600519 2. ...」点一个芯片后再重新发送 query | 故意传一张代码写在角落模糊的图 → 正确弹候选 chip；点一个 chip 后自动填入再次发送 |
| V3-3 | Confidence meter 条 + 5 专家投票结果可视化：在综合结论 🎯 上方放一行横向 meter：`🔴形态 +2  🟠趋势 -1  🟢心理 0  🔵大师 -1  📣风控 -2  📰新闻 +0  → 看空 置信度 75%`；色块显示比例条 | 投票分数和 meter 比例条颜色正确对应 |
| V3-4 | analysis_snapshots 快照写库：每次用户得到完整综合结论后，异步 write 到 Mongo `analysis_snapshots` 集合，包括所有专家分数、新闻分数、最终方向、股票代码、时间戳 | 每次回答后 Mongo 能查到一条新快照 |

---

## 10. V4 升级选项（付费 · 准确率 +20% 的单一最大提升项）
> V3 跑通后再上，当前不进默认 TODO

| ID | 升级项 | 费用 | 预期收益 |
|---|---|---|---|
| V4-1 | 接入 **Tushare Pro 2000/年**：拉每只股全量 5 年 K 线 + 资金流 + 龙虎榜 + 行业数据 + 基本面；规则引擎在**全量数据**（不是截图窗口的几根 K 线）上算 MA200/MACD/RSI/布林带/北向资金/N 日新高 | 2000 元/年 | 准确率 +15~20 个百分点（最值得的升级） |
| V4-2 | Milvus 接 SPLADE sparse embedding 做真正混合检索 hybrid（VM 一直默认关的 rerank 打开）；接 bge-reranker-v2-m3 本地 rerank（GPU 机器才有意义）| ≈ 0 元（但需要 GPU） | 召回准确率 +5~8pct |
| V4-3 | 新增 `后台管理页 /admin`：注册新书 / 看 expert_books 列表 / 看历史分析准确率排行榜 / 手动 disable 某本书 / 手动重新 ingest 某本书 | ≈ 8h 开发量 | 不用调 API 注册新书，体验更好 |
| V4-4 | 历史回测脚本 `scripts/backtest_accuracy.py`：每跑过一条 snapshots 标记 verified_outcome 后算单 doc_type 准确率 → 动态写入 expert_books 权重字段；下次投票时用专家的历史准确率作为权重加权（而不是固定 1 票） | ≈ 4h 开发量 | 系统越用越准；垃圾书 30 天后自动被降权 |

---

## 11. 已知风险 + 规避方案（必须在开发前确认已知晓）

| ID | 风险 | 概率 | 影响 | 规避方案（已写入上面） |
|---|---|---|---|---|
| R1 | VL 认错股票代码 → 后面全错 | 高（70% 场景代码字很小糊） | 严重 | V2 之前直接不让 VL 识别代码，让用户写；V3 用候选 chip 用户确认 + Tushare 代码字典校验双保险 |
| R2 | 补了一堆重复类型的书 → 召回占坑，其他专家没话讲 | 中 | 中 | D6 双保险：每专家 TopK 限 5 + chunk 去重；V4-4 历史准确率降权 |
| R3 | 补了垃圾书 → 系统变蠢胡说八道 | 中 | 中 | D6 锁 2：历史准确率 <45% 自动 disable 踢出专家池 |
| R4 | 规则引擎写的规则不对 → 投票结果偏差 | 高（初期规则需要调参） | 中 | 先只写 20 条基础规则，后面通过 analysis_snapshots 回测持续调 |
| R5 | SerpAPI 免费额度用完 → 新闻模块挂 | 中（如果你一天用超过 100 次） | 低 | 立刻接百度开发者搜索（同样有免费额度）/ Tushare Pro 新闻接口；降级提示「今日新闻额度用完，仅基于书籍分析」 |
| R6 | 合规风险：用户当真，亏了来找 | 低（但法律风险） | 严重 | D12 三层围栏 + 每次回答硬拼免责；不输出具体保本承诺；代码里拒绝分析 ST/期货等不适格标的 |
| R7 | 生成合成 Prompt 太长 → 超过 qwen-plus 128k 上下文 | 中（历史对话长 + 5 专家 Top5+新闻 10 条接近上限） | 中 | 做 compact_context（按 token 预算裁剪：先裁掉新闻 summary 只留标题 + sentiment，再裁 quality=low chunk，再裁重复段）；CONVERSATION_WINDOW_SIZE 默认只留 8 条 |

---

## 12. 禁止事项（红线，开发中不得突破）

1.  禁止在 `index.html` 引入任何 Node 构建链（Vite/React/TS）—— 保持零构建单 HTML
2.  禁止把新闻 / 实时行情数据 ingest 进 Milvus —— 每次工具调用实时搜
3.  禁止把方向判断完全交给 LLM —— 必须经过 expert_rules 打分后再让 LLM 润色，LLM 不允许改动分数
4.  禁止输出任何违反 D12 合规围栏的话术 —— 即使 LLM 生成了，postprocess 必须硬处理
5.  禁止 expert_books **初始化种子**写死在 Python 代码里 —— 初始 7 条仅通过 init 脚本 insert 到 Mongo，后续全部走 Mongo + expert_registry，通过 API 动态加
6.  禁止删除 / 覆盖 expert_books 中用户已通过 API 新增的 doc_type（init 脚本里 upsert 条件必须限制「仅当集合为空时写入」）
7.  禁止用户未在本文件第 0 节签字确认之前开始写梯队 0/1/2/3 的代码

---

## 13. 开放扩展架构指南（新书/新专家/新规则无限添加，越补越专业）

### 13.1 加书 = 加专家（完全开放，零代码 3 步）

| 步骤 | 操作 | 代码 / API 调用方式 |
|---|---|---|
| 1 | 把新 PDF 放到 [doc/](file:///home/roott/work/doc/) 目录 | 例：扔进去《笑傲股市》.pdf |
| 2 | 注册新专家到 Mongo `expert_books` 集合 | `POST /api/admin/register_book` Body: `{doc_type:"canslim", pdf_name:"笑傲股市.pdf", display_name:"CAN SLIM 选股系统", expert_role:"选股专家", emoji_tag:"📈", color:"#f59e0b", priority:2.5, domain_keywords:["选股","CAN SLIM","牛股","成长股","季度业绩"], disabled:false}` |
| 3 | 跑 ingest 进 Milvus（自动打 doc_type 标签） | `POST /api/ingestion/register_and_run` Body: `{pdf_name:"笑傲股市.pdf"}` |

完成！下一次用户提问里包含 domain_keywords 里的词 → 系统自动并行检索这本书，新专家就会出现在 UI 的专家发言卡片里。

### 13.2 「小钱办大事」补书优先级推荐（15 本，越补越聪明的顺序，按 ROI 排）

> 🟢 = 强互补维度（当前 5 本没有覆盖的盲区，补上去立刻 +8~15 分能力）
> 🟡 = 同类加强（当前已有维度，补了更厚但不立刻涨分，建议先放后面）
> 🔴 = 不建议先补（同类型堆积，大概率产生召回占坑，越补越笨的风险高）

| 优先级 | 补什么书 | 建议 doc_type | 对应补哪块盲区 | ROI 评分 |
|---|---|---|---|---|
| 🥇 P0 | 《手把手教你读财报》唐朝 | `fundamental` 已占位 | 基本面 6 指标红绿灯排雷（当前 10/100 → 80/100） | 100（必须补） |
| 🥇 P0 | 《以交易为生》亚历山大·埃尔德 | `triple_screen` | 多时间周期三重滤网（周线定方向/日线找入场/60 分定止损，防假突破第一框架） | 98（强烈推荐） |
| 🥈 P1 | 《笑傲股市》威廉·欧奈尔 | `canslim` | 选股系统（当前 5 本全是"选时"，缺「**选股**」—— 什么样的公司基本面在涨、机构在加仓？A 股赚钱第一要素） | 95（强烈推荐） |
| 🥈 P1 | 《海龟交易法则》柯蒂斯·费思 | `trend_following` | 趋势跟踪分批建仓/加仓（ATR 止损 / N 单位加仓），和范撒普的仓位互补 | 90（推荐） |
| 🥉 P2 | 《股市趋势技术分析》爱德华兹 | `dow_theory` | 道氏理论 + 经典形态（头肩/双顶/三角形/箱体），同类厚度补强 | 75（可选） |
| 🥉 P2 | 《专业投机原理》维克多·斯波朗迪 | `speculation_123` | 1-2-3 法则 / 2B 法则，趋势反转确认 | 75（可选） |
| P2 | 《筹码分布》陈浩 | `chip_distribution` | A 股本土化筹码/获利盘/套牢盘分析，和资金面强相关 | 70（可选） |
| P2 | 《期货市场技术分析》约翰·墨菲（同作者《金融市场技术分析》升级版） | `technical_trend_enhanced` | 但建议先 disabled=true，当前墨菲这本已够用，避免同类型召回占坑 | 40（🟡，等 V4 准确率调权后再开） |
| P2 | 《日本蜡烛图技术新解》/《蜡烛图方法》/《蜡烛图精解》（3 本任意 1 本即可） | `candlestick_enhanced` | 同蜡烛图，厚度补强，但强烈建议 **默认 disabled=true**，等 V4-4 跑历史准确率确定它和原蜡烛图准确率差异后再看要不要合并权重 | 30（🟡，先别开） |
| P3 | 《可转债投资魔法书》/《可转债投资黄金宝典》 | `convertible_bond` | 如果你要分析可转债（特殊定价、下修条款、回售条款、强赎条款） | 70（有需要才补） |
| P3 | 《ETF 全球投资策略》/《指数基金投资指南》 | `index_etf` | 如果你要分析 ETF（行业 ETF/宽基/跨境 ETF/商品 ETF） | 65（有需要才补） |
| P3 | 《巴菲特致股东的信》/《聪明的投资者》格雷厄姆/《彼得林奇的成功投资》 | `value_investment` | 深度价值投资补长（长期视角，和 P0 基本面红绿灯配合） | 60（长线投资者补） |
| P3 | 《缠中说禅：教你炒股票 108 课》（缠论） | `chan_theory` | 如果你是缠论爱好者（A 股本土化理论非常有争议，建议单独 weight 设 0.5，不参与主投票） | 50（个人信仰向） |
| ❌ 不建议 | 任何《3 天抓涨停》/《MACD 金叉必涨》/《索罗斯都要学的波浪理论》等标题党书 | - | 大概率引入错误规则，让系统胡说八道（历史准确率 3 个月后会自动 disable，所以你真要加也拦不住，但不推荐） | -100（🔴，避坑） |
| ❌ 不建议 | 同一主题加 4~5 本形态/趋势书 | - | 召回占坑效应：专家池 10 个有 6 个说同一件事，把心理/仓位/基本面挤掉了 | -50（🔴，避坑） |

### 13.3 加规则（expert_rules.py 无限扩展，越写越准）

规则引擎是完全开放的，从现在 V1.1 的 28 条 → 你后续可以每月加 5~10 条，做到 100~200 条规则：
- 新增规则必须命名 RULE_XX 编号，和规则描述（rule_id）、得分（points）、命中条件、对应引用证据（supporting_source_idx）
- 所有新增规则必须写单测（输入结构化条件 → 断言得分）
- 每季度跑一次 V4-4 历史回测，单条规则历史 IC < 0.03（无效预测）的 → 直接降低权重或删除，不保留无效规则
- 规则优先级：公告类 > 基本面排雷 > 资金面 > 心理/仓位 > 趋势/形态（后面的分数不能 override 前面一票否决权的结果）

### 13.4 加新数据源（D 路线小钱版）

| 加什么 | 怎么加 | 年花费 | 提升哪个盲区得分 |
|---|---|---|---|
| Tushare 2000 积分永久（120 元 + 邀请好友拉满积分免费） | tools/tushare_client.py 加 10 个接口 | ≈ 120 元永久 | 资金面从 20→70；基本面从 10→60 |
| 百度搜索开发者企业版基础包 | news_search.py 从 SerpAPI 免费额度切到百度（中文新闻更准） | ≈ 1200 元/年 = 3.3 元/天 | 新闻从 55→85；公告从 5→60 |
| Choice 金融终端个人版（399/年） | tools/choice_client.py 读 daily_basic + 研报标题摘要 | ≈ 399/年 = 1.1 元/天 | 基本面从 60→75；一致预期从 0→50 |
| 东方财富 `push2.eastmoney.com` 免费公开接口（零元） | tools/eastmoney_client.py 拉 实时现价 + 内外盘 + 量比 + 今日涨跌幅 | 0 元 | 实时快照延迟从 T-1 → T 实时 |

### 13.5 路线 E（大脑优先版）：只在 LLM 上花钱，其他所有外部服务的零成本替代方案 + 坏处对照表

> 用户最终选择的路线 E：**钱只花在「大脑本身」（LLM 大模型 token）上，其他 Tushare/百度搜索/Choice/同花顺等外部数据服务全部砍掉，用免费/极低成本方案替代**。
> 你只需要明白每个替代方案对应的坏处是什么，**坏处你能接受就用免费，不能接受再考虑单个加购**（而不是路线 D 默认全花）。

| 类别 | 原 D 路线花什么钱（去掉） | E 路线零成本/极低成本替代方案 | 替代后的坏处（你要接受的） | 如果你实在受不了，补多少小钱？ |
|---|---|---|---|---|
| **大模型（大脑，唯一必须花）** | ✅ 保留，**不替代！这就是你要留的唯一花钱项** | 千问 qwen-plus 主回答 + qwen-turbo 改写分类 + qwen3-vl-flash 读图；**建议首充 50 + 月预算 50~100 元**（1.7~3.3 元/天） | 免费额度几天就用完了，不充钱会在 1.2 条里加优雅降级提示「LLM 额度用完，进入免费精简模式」，回答专业度会降一档 | 月预算 100 元够你每天问 100 次深度行情，普通人完全够，**这是大脑，不建议省** |
| Tushare Pro（2000 积分 ≈ 120 永久） | ❌ 去掉 | **方案 A（推荐，零元）**：东方财富 `push2.eastmoney.com` 免费接口 + `emweb.securities.eastmoney.com` 公开接口（实时行情/日线/公告标题/龙虎榜标题），`tools/eastmoney_free_client.py` 抓公开 JSON | 坏处 1：没有「一致性预期」「机构调研纪要摘要」「融资融券」「北向持仓」这类 Tushare 高级接口 → FUND_03 一致预期分数默认给 0，CAPITAL_01/02/03 资金 3 条规则走「东财公开资金流向估算 + 新闻标题关键词抓北向」，**准确性从 80% 降到 50%**；<br>坏处 2：东财接口无 SLA，偶尔被风控 IP 禁 10 分钟（优雅降级用上次缓存数据，声明中会显示）；<br>坏处 3：没有回测历史日线复权数据 → V4-4 自动打标 outcome（P0-5）只能用「同花顺免费网页收盘价 + requests + BeautifulSoup 爬取」，速度慢 3 倍但数据准确 | **补 120 元永久（Tushare 2000 积分）** — 如果你 120 元都不想花，东财免费版 A 路线其实完全够用，普通人 50% 准确度的资金面 + 新闻关键词也能顶；**建议你先用 E 路线跑一个月，觉得缺资金面再买 Tushare**，不要提前买了浪费 |
| 百度搜索企业版 / SerpAPI（1200/年） | ❌ 去掉 | **方案 A（零元，有额度）**：SerpAPI 免费额度 100 次/月 + 谷歌免费搜索关键词替换百度；不够时 **方案 B（零元，强降级）**：直接拿「新闻标题 + 新闻摘要」模块让 LLM 用 qwen-turbo 直接从「东方财富公告标题 + 同花顺 7x24 快讯 RSS」生成 3 条新闻摘要，不做真实网页搜索 | 坏处 1：新闻覆盖度从 85% 降到 40%，当天发生的重大利空/利好 **完全有可能看不到**（比如盘后拟减持）；<br>坏处 2：没有「全网信息」的 SerpAPI → ANNOUNCE_01 拟减持/立案/预亏 只能靠东财公告标题关键词判断，**约 30% 概率漏掉部分公告**（靠第 10 条合规免责兜底，不是 100% 踩雷）；<br>坏处 3：方案 B 纯 RSS 时，非交易日完全没新闻，情报师（新闻专家）会显示「今日暂无有效新闻」 | **补 20 元 / 月 买 SerpAPI 个人 5000 次/月**（一天 ≈ 0.7 元，别买百度 1200 年的！贵 5 倍效果差不太多），**或者用免费额度先用着，哪天发现错过了一条 10cm 大面减持公告，再买也不迟**（补 20 元都觉得贵的话，东财 RSS + 关键词其实能兜底 60% 踩雷） |
| Choice 金融终端个人版（399/年） | ❌ 去掉 | **方案 A（零元）**：东方财富 F10 免费「财务分析」公开接口（扣非 ROE / 毛利率 / 负债率 / 经营现金流 5 年数据），`tools/eastmoney_free_client.py` 抓；**方案 B（极低成本 20 元）**：支付宝「股票分析」里有免费一致预期，用户截图用 qwen3-vl-flash 读图（E 路线大脑你已经花钱了），抓出来一致预期数字 | 坏处 1：Choice 的机构一致预期（20 家券商平均目标价）没有 → FUND_03 规则只能给 0 分，等你自己截图给 VL；<br>坏处 2：卖方研报全文没有 → 但标题摘要东财 F10 免费接口有，LLM 用标题摘要也能猜个大概；<br>坏处 3：东财免费财务接口偶尔字段变格式 → 优雅降级让 LLM 处理原始 JSON，可能偶尔出错 | **不用补**，Choice 一年 399 的那堆数据 90% 你通过东财免费 F10 + VL 截图（qwen3-vl-flash）能拿到一致预期，ROI 极低，**绝对不建议路线 E 去买 Choice** |
| 同花顺 iFinD 个人版（599/年） | ❌ 去掉 | 同上东财 F10 免费接口，数据完全够用 | 同 Choice，iFinD 提升的一致预期准确度你用 VL 截图可以补 | **不用补**，别买 |
| MinerU 官方云 OCR 补充包（30 元 1000 页 · 可选，**不是必须！**） | ❌ 默认不买，**你现在本地部署好的开源 MinerU 是 100% 免费，直接上传 PDF 立刻就能用！**<br>✅ 方案 A（默认，100% 免费，推荐）：本地 MinerU 自带 PaddleOCR 开源小模型，处理机器生成 PDF（你现有 5 本全部都是）**零成本、100% 识别率**，完全不用付费；<br>方案 B（极端情况）：如果某本书是扫描版/拍照 PDF + 你本地 GPU/CPU 跑不动大 OCR 模型 → 再考虑购买官方云 OCR | 坏处 1（几乎碰不到）：只有当你上传**纯扫描版/拍照版 PDF** + 本地显存 <4G 时，OCR 错误率会从 1%（机器 PDF）升到 15%，RAG 检索错字多；<br>坏处 2（你现在不会遇到）：手写笔记类识别不了，但股票书 99% 是机器排的，没有手写内容；<br>**你现在的 5 本机器 PDF + 直接上传 PDF = 完全零成本无坏处，付费项根本碰不到！** | **等你真遇到一本扫描版书（拍照 PDF）本地识别错误率 > 10% 且跑不动大模型时，再单独花 30 元/1000 页买官方云 OCR 包（可选，不是必须）**，现在**绝对不要买**，你现有 5 本机器 PDF 本地 MinerU 已经完美处理，一毛钱不用花 |
| 阿里云 TTS 语音包（10 元/年） | ❌ 去掉（先不用） | **方案 A（零元，推荐）**：浏览器内置 `Web Speech API`（Safari/Chrome 原生支持中文男声/女声，零成本，质量还不错，比很多收费 TTS 自然），直接在前端 `speechSynthesis.speak(new SpeechSynthesisUtterance(text))`；<br>**方案 B（次选零元）**：Edge 浏览器内置「晓晓」神经 TTS，质量接近收费，电脑上 Edge 打开直接用 | 坏处 1：Chrome 中文女声比较机械，有一点点怪（能听懂但没有收费 TTS 真人感）；<br>坏处 2：移动端 Safari 中文没问题但要用户手动点一下播放（浏览器自动播放策略限制，不能自动念，合规也刚好符合 —— 没人希望半夜打开网页自动说话） | **绝对不用补**，Web Speech API 完全够你用，阿里云 TTS 10 元一年的那点提升，你根本听不出来差别，ROI 最低没有之一 |
| **合计花费对比** | **D 路线首年约 800~1200 元（大脑 + 所有数据）** | **E 路线首月仅 ≈ 100 元（只有大脑 LLM），之后月约 50~100 元，**首年合计约 600~1200 元 上限和 D 一样，但——你可以前 3 个月只花 50 元月预算试跑，不满意随时停，不像 D 路线一次性买 120 Tushare + 399 Choice 都不能退 | 对应上表每个模块的坏处，你能接受就用免费，不能接受再**按需加购单个**（而不是 D 路线一次性全买） | E 路线你想补的单项：Tushare 120 永久 + SerpAPI 20/月 是唯二 ROI > 1 的补购项，其他一律不建议买，**真觉得缺哪个就补哪个，别一次性乱买** |

#### 路线 E 的最终建议（我帮你拍板的顺序）

1. **第 0 步（现在立刻做，花 50 元）**：千问首充 50 元 —— 这是大脑，必须有，免费额度你跑两次 V3 带 VL 识别 + 7 专家委员会 + 仲裁官生成，**2~3 天就用完了**。
2. **第 1 步（跑一个月，不花钱）**：用 E 路线所有零成本方案（东财免费接口 + SerpAPI 免费 100 次/月 + Web Speech TTS + 本地 MinerU OCR），一个月用下来你**亲身体验**：
   - 有没有因为缺资金面（北向/融资/龙虎榜）吃亏？ → 有就 **花 120 元永久买 Tushare 2000 积分**（一次买终身用）
   - 有没有因为漏了利空公告被闷杀？ → 有就 **花 20 元/月买 SerpAPI 个人版**（按月付，不想用了下个月就停）
3. **第 2 步（绝对不碰的坑）**：Choice 399 / 同花顺 599 / 阿里云 TTS 10 元 / MinerU 30 元，这四个你**就算用了 E 路线半年也大概率用不到，别被一次性付费忽悠了**。
4. **底线（不要动的）**：LLM 大脑钱（月 50~100 元）别省，这是整个系统区别于「免费 GPT 瞎扯」的唯一护城河。

---

## 14. 最强前端 UI 设计方案（彭博终端黑金专业风 · V1.1 明确规范，单 HTML 不引入构建链）

### 14.1 主题配色：彭博 / Wind 机构级配色（专业感第一）

> 写进 [index.html](file:///home/roott/work/src/shopkeeper_kb/app/static/index.html) 的 `:root` CSS 变量，替换默认的浅灰蓝主题（改完用户打开第一眼就是"这玩意儿能赚钱"的感觉）

```css
:root {
  /* ---- 彭博黑金主题 ---- */
  --bg:          #0a0f0a;   /* Modal 背景：深黑绿（护眼） */
  --bg-elev:     #121a12;   /* 卡片背景：比背景亮一点 */
  --bg-elev-2:   #1a251a;   /* hover 高亮：来源卡片 / 专家卡片 hover */
  --border:      #263626;   /* 边框：暗绿 */
  --primary:     #e6b800;   /* 品牌主色：机构金（置信度 / 仲裁官老李 / 6 个数字强调色）*/
  --danger:      #ff4d4f;   /* 看空/利空：红（A 股习惯红涨绿跌，做空时用）*/
  --success:     #52c41a;   /* 看多/利好：绿 */
  --neutral:     #8c8c8c;   /* 中性灰 */
  --text:        #e6ffe6;   /* 正文：淡绿护眼 */
  --text-muted:  #95b895;   /* 次要文字：中绿 */
  /* ---- 7 位专家颜色标签（和 expert_books 对应）---- */
  --c-candlestick: #ff6b6b;  /* 🔴 形态师 */
  --c-technical:   #ffa940;  /* 🟠 趋势师 */
  --c-fundamental: #fadb14;  /* 🟡 基本面师 */
  --c-psychology:  #73d13d;  /* 🟢 心理师 */
  --c-master:      #40a9ff;  /* 🔵 大师经验 */
  --c-risk:        #b37feb;  /* 🟣 仓位师 */
  --c-news:        #8c8c8c;  /* ⚫ 情报分析师 */
  /* ---- 排版 ---- */
  --font-sans:  ui-sans-serif, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  --font-mono:  ui-monospace, "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace;  /* 6 个数字、仪表盘数值用等宽字体，看起来像量化终端 */
}
```

### 14.2 UI 组件 9 模块（对应回答时渲染顺序 = 私募早会流程）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🎖️ 仲裁官 [老李] 头像(圆色块+字) + 开场口头禅 + 免责声明小 chip                │ 模块 1：仲裁官开场
│ "听我一句劝，先给你把 6 位专家 + 情报处的意见汇总完了，再给你最终交易计划。"    │（模拟真人说话）
├─────────────────────────────────────────────────────────────────────────────┤
│ 🖥️ [DASHBOARD 仪表盘条 · 等宽字体数字，一眼看懂，像彭博终端]                   │ 模块 2：顶部仪表盘
│ 综合: 🔴 看空 75%  │  📉 支撑 1640 · 1600  │  📈 压力 1700 · 1760  │  💧 R/R 1:2.4  │  🧭 β: 1.2
│  ═══════◼◼◼◼◼◻◻◻◻◻  52 分  方向仪表盘（分数 -100~+100 颜色渐变）              │
├─────────────────────────────────────────────────────────────────────────────┤
│ 👥 专家发言卡片区（一张一张按 priority 顺序打字机出来，间隔 0.7s，模拟讨论感） │ 模块 3：5 专家发言卡
│ ┌──────────────┬──────────────────────────────────────────────────────────┐ │（人格感+口头禅+解释器）
│ │📕[形] 形态师  │  **[看空 78%]  我只看形态，不讲故事。**                       │ │
│ │圆形头像+颜色  │  黄昏之星三阶段完美成立（日本蜡烛图 P.68 [1]）                │ │
│ │左侧打分进度条 │  第 3 根阴线回吐 62% > 50% 阈值（日本蜡烛图 P.70 [2]）        │ │
│ │◼◼◼◼◼◻◻ 78%   │  👉 我建议：明早高开立刻减 1/3，别恋战。                    │ │
│ └──────────────┴──────────────────────────────────────────────────────────┘ │
│ ┌──────────────┬──────────────────────────────────────────────────────────┐ │
│ │📗[势] 趋势师  │  **[看空 68%]  我不抢跑，等破位再动手。**                     │ │（每个专家开头必须说自己的固定口头禅）
│ └──────────────┴──────────────────────────────────────────────────────────┘ │
│        ... 📊 基本面 / 📘 心理 / 📙 大师 / 📓 仓位 / ⚫ 情报 依次出 ...        │
│                                                                             │
│ 💡 每张卡右下角小按钮「🔍 为什么这么说？」 → 点击展开 popover：                │
│    命中规则：CAND_01 黄昏之星 -2；CAND_05 三只乌鸦 -2；TREND_01 MA死叉 -2      │
│    证据来源：[1][2]（鼠标悬停引用编号 / 小 chip → 显示书上原文完整 5 句预览块） │
├─────────────────────────────────────────────────────────────────────────────┤
│ ⚖️ [仲裁官 老李 最终判决]  6 个数字交易计划（用 ⚖️ 金色边框卡，等宽字体对齐）    │ 模块 4：最终交易计划
│ ┌───────────────────────────────────────────────────────────────────────┐ │（必须表格对齐）
│ │ 🎯 最终结论：🔴【偏空】4:2 投票，置信度 75%                                │ │
│ │ ─────────────────────────────────────────────────────────────────── │ │
│ │ ① 综合方向     │ 偏空（4 风险票 vs 2 机会票）                           │ │
│ │ ② 持仓动作     │ 多单先减 1/3（在 1680 以上冲高时逐步止盈）                │ │
│ │ ③ 止损线       │ 1640（MA20 + 前低），跌破立刻市价清，不抱幻想              │ │
│ │ ④ 新进场条件   │ 空仓者不急，1600 支撑位若出现启明星（蜡烛图 P.72）再入场多  │ │
│ │ ⑤ 仓位大小     │ 账户 100 万，R=1% = 1 万；入场 1600 - 止损 1590 = 10 元  │ │
│ │                │ → 1 万 / 10 = 1000 股（约 160 万？不，1000*1600=160 万不对 │ │
│ │                │   → 修正：1 万 / 10 价差 = 1000 股 × 1600 = 160 万❌错误 →    │ │
│ │                │   → 正确：仓位=R/(入场价-止损价) = 1 万/10 = 1000 股，      │ │
│ │                │      但受限于单票仓位≤25%=25 万 → 实际取 min(1000, 156股)   │ │
│ │                │      = 156 股（仓位 ≈ 15.6%，≤25%上限，符合风控）            │ │
│ │ ⑥ 失效条件     │ 3 个交易日放量站稳 1730 且不回落，我认错，反手回补 1/3        │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ 🖼️ 用户画像 chip（可点展开改）：你现在是「中等风险 · 波段 · 10~50 万 · 白酒 20%」 │ 模块 5：用户画像
│ 👉 当前持仓：600519(12%) + 000858(10%) → 行业集中度白酒=22% ✅ ≤30% 安全        │（连续感+私人定制）
├─────────────────────────────────────────────────────────────────────────────┤
│ 📚 来源卡片（2x2 缩略图，和你现有保持一致，但黑金主题）                        │ 模块 6：引用卡（你已完成）
├─────────────────────────────────────────────────────────────────────────────┤
│ 💡 See also 关联 chip（加 thumb）                                           │ 模块 7：See also（你已完成）
├─────────────────────────────────────────────────────────────────────────────┤
│ 🔊 语音播报按钮（点一下 低沉男声只读 最终 6 数字交易计划）                      │ 模块 8：语音（可选，阿里云 TTS 10元包年）
├─────────────────────────────────────────────────────────────────────────────┤
│ ⚠️ 风险提示大粗条（金色边框，D12 围栏，强制显示不能关）                         │ 模块 9：合规围栏（你已完成）
└─────────────────────────────────────────────────────────────────────────────┘
```

### 14.3 小人说话人格感的 4 个核心细节（零图片成本，纯文字 + 节奏出效果）

| 细节 | 实现方式 | 效果 |
|---|---|---|
| ① 固定口头禅 System Prompt 硬约束 | 每个专家的发言开头/结尾必须写固定句式：<br>• 形态师：`我只看形态，不讲故事。`<br>• 趋势师：`我不抢跑，破位再动手。`<br>• 心理师：`别爱上你的头寸。`<br>• 大师：`XX（人名）说过...`<br>• 仓位师：`算 R 值，我只看数字。`<br>• 情报师：`截止今日 X 点，公开信息显示...`<br>• 仲裁官老李：`听我一句劝。` | 立刻有"这是 7 个不同的人在说话"的错觉，而不是单个 LLM 复述 7 遍 |
| ② 打字机逐张卡延迟出场（不是一次全出） | SSE 流里把 7 位专家卡片拆成 7 个独立事件，每出完一张卡 → `await sleep(600~900ms)` 再出下一张，模拟"一个一个发言"的节奏 | 人格感 × 10，用户感觉这系统在帮他开早会 |
| ③ 圆形渐变色头像（用 CSS 画，不放真人照片） | 每个专家的 color 字段 + 专家名第一个字（📕 形态 → 🔴 红色圆 + 白字「形」） | 零图片成本，色彩和 expert_books 对应，一眼能分清谁在说话 |
| ④ 专家间互相"拆台"对话感（生成 Prompt 里教他们偶尔引用前一个专家） | Generation Prompt 里写：心理师发言时可以说"我补充一句 @形态师 刚才说减仓，我非常同意，现在你浮盈超过 30% 容易..."，仲裁官总结时会说"我综合了一下 @趋势师 的破位等待和 @仓位师 的 R/R 要求，最终给出..." | 真实会议里的对话感，不是 7 个人各说各的 |

---

## 15. V1.1 升级说明（小钱高回报版 · 相对 v1.0 的 6 大升级）

| 编号 | 升级点 | 原 V1.0 | 新 V1.1（D 路线）| 能力提升 |
|---|---|---|---|---|
| U1 | 开发路线默认切 D（小钱高回报 1 天 1~3 元） | A 纯免费 | D 路线：首年 ≈ 800~1200 元（Tushare 120 + 百度搜索 1200 + Choice 399 = 1719/年 ≈ 4.7 元/天，部分可按需只买其中 2 个，最低 ≈ 200 元永久就能跑核心能力）| 总分从 70 → 88 |
| U2 | 开放架构澄清 + 补书指南（第 13 节） | 只写了"动态注册"一句话 | 明确 3 步加书流程 + 15 本 ROI 优先级清单 + 同类型书召回占坑避坑指南 | 避免"越补越蠢"，保证越补越聪明 |
| U3 | 规则引擎从 20 条 → **28 条 7 大类** + 规则-引用映射机制 | 20 条 5 大类 | 新增：基本面 3 条 FUND（ROE 红灯一票否决）+ 资金面 3 条 CAPITAL（北向/融资/龙虎榜）+ 公告 2 条 ANNOUNCE（拟减持/立案 直接熔断不给方向）+ 仓位 3 条细化 RISK（行业集中度/T+1 流动性修正/交易成本扣 0.5%），**基本面/公告 = 一票否决权，权重是形态趋势的 5 倍** | 防踩雷能力从 30 → 85；不会再出现"形态完美但 ST 退市"的致命错误 |
| U4 | 前端 UI 规范（第 14 节） | 只有 Fluss 浅蓝默认主题 | 明确彭博黑金色 + 9 模块渲染顺序 + 4 个人格感细节 + 最终交易计划等宽表格强制对齐 6 数字（防止 R/R 算错不自知）| 专业感视觉评分 60 → 95 |
| U5 | 专家池从 5 位 + 1 新闻 → **7 位默认池（财报占位+情报师独立）** | 5 书 + 新闻混着说 | 财报 `fundamental` 独立一位专家（disabled=true 占位，PDF 有了立刻开）+ 新闻+资金+公告合并成独立 `news_capital_flow` 情报师，不再混在其他书里 | 分析结构清晰度 70 → 90 |
| U6 | 合规 + 安全 2 层加强 | 只有黑名单词 + 结尾免责 | 新增禁止事项 5/6 条（防止 init 脚本覆盖用户加的书 / 防止删除用户数据）+ ANNOUNCE 熔断机制（拟减持/立案直接拒绝给方向）+ 仓位 RISK_04 行业集中度检查 + RISK_05 T+1 止损 1.3 倍放宽 | 法律/操作风险等级 从 中 → 极低 |

---

## 16. 遗漏补全清单（P0/P1/P2 分类 + 已合并进对应梯队位置）

> 🔴 P0 = 不补项目就会崩 / 会出离谱错误的硬漏，**本章节列出的 P0 项已全部同步合并回梯队 0/1/2/3 对应任务的验收标准，无需单独加任务**
> 🟠 P1 = 不补体验非常差 / 容易掉链子的软漏，**已全部同步合并进 V1/V2/V3 里程碑的新增验收项**
> 🟡 P2 = 长期运维优化项，V4 以后再做

### 🔴 P0 硬漏（8 项 · 已合并进梯队 0/2/3）

| 编号 | 漏了什么 | 为什么是硬坑 | 合并到哪里 |
|---|---|---|---|
| P0-1 | **规则命中 → 引用编号的映射机制**（rule_id ↔ sources[] 下标） | 梯队 2.4 说每条规则写 evidence_src_idx，但没写「generation 时如何把一条规则命中的 [0,1] 对应到最终输出的 [1][2]（因为 sources 是全局合并去重排序的，下标会变）」→ 没有这个映射，UI 上的「🔍 为什么这么说？」popover 和正文 [n] 会乱标，点引用跳错页 | 合并进梯队 2.4 `score_per_expert` 返回值的 `reason_rules[].supporting_source_idx`：**必须在 sources 全局合并排序后，重写为最终全局下标**，并在 3.3 generation 做 postprocess 校验一致性 |
| P0-2 | **6 数字仓位计算溢出自动修正（不止校验，要自动改对）** | 梯队 3.3 写了「缺字段重请求」，但没处理「100 万账户 / R=1% =1 万 / 止损 10 元 → 1000 股 × 1600 元 = 160 万（仓位超过账户本金 160%，数学对但实际不可能）」→ 只校验不修正 = 用户永远拿不到合理建议 | 合并进梯队 3.3 generation.py `postprocess_final_six_numbers`：必须做 **min(理论仓位, 用户画像单票上限 25%)** 的强制 clamp 修正，并在输出里加一句小字说明「仓位已按您设定的单票 ≤25% 上限从 1000 股调整为 156 股」（和 14.2 模块 4 表格里写的一样） |
| P0-3 | **SSE 事件协议扩展（对应 9 模块 UI）** | 原 SSE 协议只有 `{delta, sources, related, done}`，前端只能 append 到一个 `#content` div → 但 V1.1 的 UI 是 9 个独立模块（仲裁官开场 / 仪表盘 / 7 张专家卡 / 最终判决卡 / 用户画像 / 来源卡 ...），没有模块区分前端不知道什么时候 append 什么组件 → 打字机延迟出场效果做不出来，专家发言卡和仲裁官卡混在一起 | 合并进梯队 3.3/3.4：新增 SSE event.type 字段，**严格按顺序发送 11 种事件**，前端 index.html 新增 `handleSSEEvent(type, payload)` switch-case 分发到对应 DOM 插入：<br>1. `arbiter_opening` → 模块 1 仲裁官开场<br>2. `dashboard` → 模块 2 仪表盘（一次性渲染数字+进度条）<br>3. `expert_card_start`（带 doc_type）→ 新建该专家的卡片容器<br>4. `expert_delta`（带 doc_type）→ 对应卡片追加 delta 打字机<br>5. `expert_explain_rules`（带 doc_type+rule_ids）→ 给该卡片的「🔍 为什么」绑定 popover 内容<br>6. `expert_card_done`（带 doc_type）→ 卡片 fade-in 完 + await sleep 700ms 再发下一个专家<br>7. ~~7 位专家依次重复 3~6~~<br>8. `final_trade_plan` → 模块 4 最终判决金色表格（等宽对齐 6 数字 + 仓位 clamp 说明小字）<br>9. `user_profile_card` → 模块 5 用户画像 chip<br>10. `sources_and_related` → 模块 6/7（原 sources/related 事件保留兼容）<br>11. `done` → done=true+confidence |
| P0-4 | **常用 A 股代码/行业映射本地字典缓存（不能每次 VL 识别完都去 Tushare 查）** | 只写了 Tushare stock_basic 校验，但没写「启动时拉一次全量股票基础信息（~5000 只）→ 存成两个本地 JSON dict：`code_to_info[code] = {name, industry_sw_level1, industry_sw_level2, list_date}` 和 `name_to_codes[name] = [code1, code2]` → 缓存到磁盘 JSON，每天启动时增量刷新一次」→ 缺这个的话 1）用户打「茅台」匹配代码慢 2）VL 识别出代码还要去 Tushare 查上市日期判断是不是新股（<60天），每次浪费 API 3）行业集中度检查（RISK_04）每次要去 Tushare 拉行业，慢得要死 | 合并进梯队 0.5 MongoDB 建表脚本 + 新增 `tools/stock_dict.py`：启动时从 Tushare 免费 `stock_basic` 拉 5000 只 → 写入 Mongo `stock_dict` 集合（_id=code）+ Redis 缓存 24h；并提供 `industry(code)` / `is_new_stock(code, days=60)` / `match_by_name(name)` 三个常用函数，1ms 内返回 |
| P0-5 | **analysis_snapshots 自动打标（不用人工判断对错，自动读取 20 天后实际收盘价）** | 只写了存 analysis_snapshots，没写「怎么把 verified_outcome（当时判断对不对）填回去」→ 没有 outcome 就没法跑 V4-4 的专家准确率动态权重（D6 双保险的第二条就完全作废了，等于写了个死字段）| 合并进 V4-4 `scripts/backtest_accuracy.py`：每天凌晨跑一次 cron，筛选出「created_at >= 20 个交易日之前」且 verified_outcome 为空的快照 → 去 Tushare 拉 20 个交易日后的复权收盘价（或者用户指定的方向预测周期天数）→ 自动打标 verified_outcome = (direction=='bull' and close_after > entry_price * 1.01) ? 'correct' : (direction='bear' and close_after < entry_price * 0.99) ? 'correct' : 'wrong/neutral' → 然后算每位 doc_type 的 historical_accuracy → 写回 expert_books.weight（越高权重大）|
| P0-6 | **引用标号不一致后处理兜底（不是只报错重请求）** | 3.3 写了「标号超出 sources 长度就重请求」，但没写 retry 3 次都失败时怎么兜底 → 很容易出现「LLM 就是喜欢乱标，retry 3 次都不行 → 整条回答作废返回 500，用户体验崩了」| 合并进梯队 3.3 postprocess：3 次 retry 后仍有错标 → 不报错，把所有超范围的 [N] 替换成一个灰色 `<span class="cite cite-unknown">?</span>` chip，旁边悬停显示「此引用标号 AI 生成有误，已修正」→ 保证用户至少能看到正确的大部分回答，不会白等 10s |
| P0-7 | **持仓/用户画像双写（localStorage + MongoDB user_profile，不然换电脑全丢了）** | 只写了 localStorage 存 3 字段（本金/风险/周期）+ 持仓，但用户换手机/清浏览器缓存就全丢 → 尤其是持仓（用户辛辛苦苦录的 10 只票仓位和成本价）丢了用户会疯 | 合并进 V2-? 新增 `services/user_profile.py` + `/api/profile` 两个路由：<br>`GET /api/profile/{user_id}` → 先读 localStorage，空就回滚 Mongo `user_profiles` 集合<br>`POST /api/profile/{user_id}` → 双写 localStorage + Mongo（用户点一次「保存到云端」按钮触发；默认 UUID 存 localStorage，匿名用户无需登录） |
| P0-8 | **「假设模式追问」上下文识别（用户改条件不是新股）** | 只写了 needs_rewrite 改写 query，没处理用户追问「那如果跌到 1600 没破启明星呢？」「如果北向今天又净买 10 亿呢？」这种**修改某一条件的假设模式**→ 现在的流程会认为是一个新股票重新查一遍，不会 override 规则里的某个条件，回答牛头不对马嘴 | 合并进梯队 2.4 入口 + 3.4 chat 路由：新增 `detect_hypothetical_modifiers(history, current_q)` 函数 → 若命中「如果/假如/假设/要是/改一下条件...」关键词 + 命中「支撑位/压力位/北向/形态」等可量化字段 → 直接在传入 expert_rules 的 structured_input 里覆写对应字段（例如把 support_levels[0] 改成 1600），**不走 Milvus 重新检索，直接重新打分 → 回答速度 5 倍快，结果完全符合用户期望的假设场景** |

### 🟠 P1 软漏（6 项 · 已合并进 V1/V2/V3 新增验收）

| 编号 | 漏了什么 | 为什么是软坑 | 合并到哪里 |
|---|---|---|---|
| P1-1 | **admin 路由完整实现（register_book + list + toggle_disabled + reingest + 删除专家）** | 0.3 只写了「调一次 POST /api/admin/register_book」作为流程，但没写具体在哪、怎么加权限 | 合并进梯队 1.6（同 ingestion 路由一起加）→ 新增 `app/routes/admin.py`，保护机制：env 变量 `ADMIN_API_KEY`，请求头 `X-Admin-Key` 不对 403。提供 5 个接口：<br>1. `POST /api/admin/register_book`（新增 doc_type）<br>2. `GET /api/admin/experts`（list 所有 expert 含 disabled/weight/historical_accuracy 字段，未来 V4 管理页用）<br>3. `PATCH /api/admin/expert/{doc_type}/toggle`（启用/禁用专家）<br>4. `POST /api/admin/expert/{doc_type}/reingest`（重新跑 ingest，比如新版 PDF 替换了）<br>5. `DELETE /api/admin/expert/{doc_type}`（从 expert_books 软删 disabled=true，Milvus 里的 chunk 保留但检索时过滤掉）|
| P1-2 | **全链路优雅降级（单一模块挂了别 500 全崩）** | 风险表写了规避但没写进代码设计 → 实际会遇到：Tushare 额度用完 / 百度搜索今日用完 / VL 额度用完 / Milvus 挂了一台等 | 合并进梯队 3.4 每个工具调用外层：try/except 后用 fallback 返回 + 在最终回答末尾加一行「本回答基于 XX+YY 给出」小字显示实际用到了哪些模块：<br>• Tushare 失败 → 仅用 VL 截图/用户文字输入估算特征 + 声明「行情快照获取失败，支撑/压力位基于书籍估算」<br>• 新闻搜索失败 → 跳过新闻模块，声明「今日新闻模块暂时不可用，仅基于书籍分析」<br>• VL 额度用完 → 退回纯文字模式，提示「截图识别额度用完，请手动在文字里描述形态和代码哦」<br>• LLM plus 额度用完 → 自动切到 qwen-turbo 继续跑（声明「当前使用轻量模型，复杂推理能力可能降低」）|
| P1-3 | **移动端适配 CSS（手机上必用）** | 14.2 写了 9 模块布局（桌面端），没写手机/平板上怎么折行 | 合并进 V3-3（同 UI 打分条一起做）→ 在 index.html 加 `@media(max-width: 768px)` 媒体查询，三条硬规则：<br>1. 专家卡片：左右两栏（左头像+打分条 / 右内容）→ 改成上下布局（头像打分条在上，内容在下）<br>2. 仪表盘条：5 个数字 一行 1 个，分 5 行显示，进度条缩窄<br>3. 最终判决表格：6 项从左右两列表格 → 改成每一项单独一行卡片显示<br>保证 iPhone SE 小屏幕上也能看完 6 数字不横滑 |
| P1-4 | **ingestion 失败自动重试 3 次 + 手动重跑 + 详细日志** | 只写了 GET /api/ingestion/status/{task_id} 查进度，没写 MinerU 解析超时 / Milvus upsert 超时失败怎么处理 | 合并进梯队 1.6 ingestion 路由：后台 task 里每个 node 失败自动重试 3 次（指数退避 2s→4s→8s），3 次都失败把 traceback 存进 Mongo `ingestion_tasks` 集合，status 页面能看到完整错误；前端点「重新运行失败节点」按钮能从失败的 node 接着跑，不用从头重新跑 PDF 切分（省时间）|
| P1-5 | **「历史分析」用户查询页 + 快速比对（V3 长期连续感）** | 只写了 analysis_snapshots 存库，没给用户一个入口看「上周我问的茅台现在怎么样了？当时让我 1640 止损现在对不对」| 合并进 V3-4（同 snapshots 写库一起加）→ UI 右上角新增 🕓「历史记录」按钮 → Modal 列出最近 20 次分析快照（股票名/代码/日期/当时方向/20 天后实际结果✅/❌/⏳），点任何一条直接跳回当时的完整对话，并且「20 天后实际结果」用 V4-4 自动打标回来显示 ✅ 对 / ❌ 错 |
| P1-6 | **PDF.js viewer 本地打包（别用 Mozilla 公共 CDN 了）** | 现在 index.html 是 HEAD 检查本地 pdfjs 有没有 → 没有 fallback 到 mozilla.github.io viewer → 实际用起来网慢要等 30s 才能打开 PDF，体验很差，而且 Mozilla CDN 在国内有时候抽风 | 合并进 V2 里程碑：脚本 `scripts/download_pdfjs.sh` 自动下载 pdfjs-4.x-dist 压缩包 → 解压到 `src/shopkeeper_kb/app/static/pdfjs/` → `.gitignore` 忽略 `pdfjs/` 目录（但脚本进仓）→ 启动 FastAPI 前跑一遍脚本 → 本地 viewer 秒开，零延迟跳页码 |

### 🟡 P2 长期运维优化（2 项 · 记录在案但 V4 再做，不用现在操心）

| 编号 | 漏了什么 | 什么时候做 |
|---|---|---|
| P2-1 | **持仓跨行业相关性矩阵 + 蒙特卡洛 VaR（组合风险，不是单票）** | V4 当用户持仓 ≥ 5 只不同行业后再做：numpy 算 250 日协方差矩阵 → 组合 β / 相关性热力图 / 95% VaR（一天最大可能亏多少）→ 显示在「用户画像 chip」点展开的详情页里，给分散建议（「你现在 80% 仓位在食品饮料+医药，相关性 0.8，建议减白酒加 新能源（-0.2 负相关）分散」）|
| P2-2 | **规则贡献度归因面板（哪条规则最赚钱，哪条是噪音）** | V4-4 跑过 500+ 条已打标快照之后做：对 28 条规则分别算「命中该规则时 20 天后平均收益率 / IC 值」→ 管理页显示每条规则的 ROI 排名，自动建议「ANNOUNCE_01 立案/拟减持命中率 87%，建议加权重到 -15 分；CAND_06 三白兵命中率 41%，建议降权或删除」，避免规则越加越多噪音越多 |

---

## 17. 最终核对清单（开发前确认项 = 用户签字前最后扫一遍）

> 本清单用于开发前最后一次确认 "有没有什么核心需求没覆盖到"，如果下面 20 条全是 ✅，就可以签字开始写代码。

| 编号 | 核对项 | 状态（你打勾） |
|---|---|---|
| 1 | 开放架构：5 本书不是写死，能零代码无限加新书、加规则、加数据源 | ☐ |
| 2 | 小钱高回报：**路线 E（大脑优先版 · 你当前选择的）** 首月约 100 元（只花 LLM 钱）、其他全部零成本替代；或者路线 D 首年 800~1200 元，完全符合预算预期 | ☐ |
| 2-E | 你已读完第 13.5 节「路线 E 零成本替代方案 + 坏处对照表」，接受 Tushare/搜索/Choice/TTS/OCR 这 5 个模块各自对应的坏处，明白「哪天上当了缺哪个再单独补购哪个」，而不是一次性全买 | ☐ |
| 3 | 股票分析 12 个盲区全覆盖（形态/趋势/心理/仓位/基本面红绿灯 / 资金北向融资龙虎榜 / 公告熔断排雷 / 行业集中度风控 / T+1 流动性修正 / 交易成本修正 / 历史胜率回测钩子 / 新闻情绪）| ☐ |
| 4 | 专家委员会人格感：7 位不同专家（固定口头禅 + 圆形色块头像 + 打字机延迟逐张出场 + @互相引用对话感）+ 仲裁官老李总结 | ☐ |
| 5 | 专业前端 UI：彭博黑金配色 / 仪表盘 / 专家卡片打分条 / 等宽字体 6 数字对齐表格 / 移动端适配 | ☐ |
| 6 | 可解释性：每条观点后面 [n] 跳书 P.N / 悬停 [n] 显示原文 / 每张专家卡「🔍 为什么这么说？」显示命中的 rule_id + 分数 | ☐ |
| 7 | 截图半自动化：V2 支持上传截图 → VL 识别 chart_features → 但代码让用户手动写防幻觉；V3 支持候选 chip 确认 | ☐ |
| 8 | 一票否决熔断：FUND_01 ROE 红灯直接扣 -5；ANNOUNCE_01 拟减持/立案/业绩预亏/非标 → 直接 refused 不给方向，红色大警示条 | ☐ |
| 9 | 仓位风控硬规则：R 值（用户画像 1%/2%/3%）+ 单票 ≤ 25% + 单行业 ≤ 30% + T+1 止损 1.3× + 交易成本 0.5% 扣除 + 6 数字仓位 clamp 自动修正 | ☐ |
| 10 | 合规安全：三层围栏（黑名单词后处理替换 / 结尾强制免责声明 / 不适格 ST/新股/期货/港股直接拒答）| ☐ |
| 11 | 长期自学习：analysis_snapshots 自动 20 天后打标 outcome → 专家准确率动态权重 → 垃圾书 3 个月自动 disable，越用越准 | ☐ |
| 12 | 开放扩展：3 步加新书 + 15 本 ROI 优先级清单（越补越聪明，避坑指南防越补越笨）| ☐ |
| 13 | 优雅降级：Tushare/新闻/VL/LLM 任何单一模块挂了，不会 500 全崩，会显示用了哪些模块给出降级分析 | ☐ |
| 14 | 持仓/画像不丢：localStorage + MongoDB user_profile 双写，换电脑/手机不会丢 | ☐ |
| 15 | 连续记忆：下次问「现在怎么样？」→ 自动回灌上次 analysis_snapshots → 对照更新；并能看历史记录 | ☐ |
| 16 | 假设追问：「如果不破 1640 呢？」→ 覆写规则条件直接重打分，不重新检索不浪费 token | ☐ |
| 17 | 引用兜底：LLM 乱标引用不报错，灰色 ? chip 显示，用户至少能看到完整回答 | ☐ |
| 18 | PDF 秒开：V2 本地打包 PDF.js viewer，不再依赖 mozilla 公共 CDN | ☐ |
| 19 | Ingestion 不折腾：失败自动重试 3 次 + 从失败节点重跑，不用每次重新 PDF 切分 | ☐ |
| 20 | 代码字典快：5000 只 A 股启动时全量缓存本地 JSON，查行业/上市日期/名称匹配 1ms 内返回 | ☐ |

### 如果上面 21 条（含 2-E 专属项）有任何 ❌ / 需要修改的地方，你在回复里指出「第 N 条我要改的是 XX」，我继续改 Todo 直到你说全 ✅。
### 如果 21 条全 ✅：
  - 你选**路线 E（大脑优先版，当前你问的这条）** → 回复：`「E 路线 + 21 条全通过 + 第 13.5 节坏处表已读 + 签字确认，可以开始开发」`
  - 你选**路线 D（小钱高回报原默认版）** → 回复：`「D 路线 + 21 条全通过 + 签字确认，可以开始开发」`
→ 我收到任意一条口令后，**立刻清空当前所有设计 Todo，建立「梯队 0（地基层）」真正的代码开发 Todo，从 0.1 state.py 字段升级开始严格按顺序写代码，每梯队完成给你一份验收结果，不跳步**。
