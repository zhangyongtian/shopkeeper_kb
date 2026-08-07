from typing import Literal, NotRequired, Required, TypedDict


class MDImgItem(TypedDict):
    """
    Markdown 图片一次出现（occurrence）的结构化信息。

    字段说明：
    - img_rel_path: Markdown 中图片的原始路径（通常为相对路径）
    - img_abs_path: 图片在本机文件系统中的绝对路径（用于多模态模型读取）
    - alt: Markdown 图片的 alt 文本，即 ![alt](...) 中的 alt
    - pre_text: 图片标记前的上下文文本片段（固定窗口左侧）
    - next_text: 图片标记后的上下文文本片段（固定窗口右侧）
    - start: 图片 Markdown 片段在 md_content 中的起始下标
    - end: 图片 Markdown 片段在 md_content 中的结束下标
    - exists: img_abs_path 指向的文件是否存在
    - img_desc: 图片经大模型解析后的内容信息（后续节点填充）
    - minio_url: 图片写回后的可访问 URL（通常来自 MinIO 公网地址）
    """
    img_rel_path: str
    img_abs_path: str
    alt: str
    pre_text: str
    next_text: str
    start: int
    end: int
    exists: bool
    img_desc: str
    minio_url: str


class Chunk(TypedDict):
    """
    结构化切分结果（顶级切分：结构化 + token-aware + 展示/检索解耦）。

    字段说明：
    - doc_id: 文档稳定标识（用于增量更新、跨文件去重）
    - doc_type: 该 chunk 归属的专家 doc_type（对齐 expert_books.doc_type；用于 Milvus 召回时按专家 TopK 过滤 / 权重调参，开放扩展架构的唯一字段，不要写死在 Python）
    - chunk_id: chunk 的稳定标识（用于入库/溯源/去重）
    - chunk_level: chunk 层级（通常为 child；可扩展 parent）
    - parent_id: 章节/父级聚合标识（常与 section_path 一一对应）
    - section_path: 章节路径（标题链），用于提供语境与聚合
    - position: chunk 在文档中的顺序号（从 0 开始）
    - page_number: chunk 对应在原 PDF 中的页码（P.N，用于引用标号跳页 + 悬停原文预览；MinerU 解析时回填，解析不到则置为 -1）
    - token_count: embed_text 的 token 估算值（用于预算控制与调参）
    - embed_text: 用于向量化的纯语义文本（去 URL、融合图片语义）
    - display_text: 用于展示的 Markdown 原文（保留图片/表格/列表等）
    - image_urls: chunk 内关联图片 URL（用于前端展示）
    - image_alts: chunk 内图片的 alt/caption（用于检索与展示提示）
    - quality: 内容质量标签（normal/low），用于去噪、降权或过滤
    """
    doc_id: str
    doc_type: str
    chunk_id: str
    chunk_level: str
    parent_id: str
    section_path: str
    position: int
    page_number: int
    token_count: int
    embed_text: str
    display_text: str
    image_urls: list[str]
    image_alts: list[str]
    quality: str


class ImportGraphState(TypedDict, total=False):
    """
    ImportMainGraph 全链路状态（对应梯队 1 ingestion pipeline 的 8 阶段 → 切分为 7 个 Node 串行）。
    状态字段按节点生命周期顺序排列，便于读代码时一眼看到「上一节点产出 / 下一节点消费」。
    """

    # ============== N0 入口（路由层 / 调用方传入） ==============
    task_id: Required[str]              # 任务唯一键（ingestion_tasks.task_id）
    user_doc_type: str                  # admin/调用方声明的 doc_type（candlestick / technical_trend…）。空则由 item_name 节点推断。
    request_id: str                     # X-Request-Id（trace 用）

    is_md_read_enabled: bool            # N0 NodeEntry 设置的 MD 分支（是否走 NodeMDImg / NodeDocumentSplit）
    is_pdf_read_enabled: bool           # N0 NodeEntry 设置的 PDF 分支（是否走 NodePDFToMD）
    pdf_conversion_done: bool           # NodePDFToMD 成功后标记为 True（供条件边路由）

    local_dir: str                      # 本地目录路径（可选）
    local_file_path: Required[str]      # 本地文件路径（NodeEntry 要检查是否存在）
    file_title: str                     # 文件标题（文件名 stem，作为 chunk 展示名兜底）
    pdf_path: str                       # PDF 文件路径
    md_path: str                        # Markdown 文件路径

    # ============== N1 NodePDFToMD / NodeEntry 产出 ==============
    md_content: str                     # Markdown 文件内容（NodePDFToMD 或 NodeEntry（MD 分支）写入）
    pdf_page_count: int                 # PDF 总页数（pypdf 读的，NodeMDImg/NodeDocumentSplit 反推 page_number 用）

    # ============== N2 NodeMDImg 产出 ==============
    md_img_items: list[MDImgItem]       # 多模态图片识别+上传后的结构化列表

    # ============== N3 NodeItemNameRecognition 产出（主体识别 + doc_type 推断） ==============
    item_name: str                      # 识别到的主体名称：书名 / 报告名（如"日本蜡烛图技术"）
    item_type: str                      # 主体类型：book / research_report / announcement / trading_rules / other
    item_tags: list[str]                # 主体标签（["股票","技术分析","日本蜡烛图"]）
    doc_type: str                       # 推断/声明后的最终 doc_type（与 expert_books.doc_type 对齐，7 专家召回用）
    display_name: str                   # 展示名（admin 专家书库列表、sources 引用卡「书名」展示用）

    # ============== N4 NodeDocumentSplit 产出 ==============
    chunks: list[Chunk]                 # 分块内容列表（结构化：用于检索与展示）

    # ============== N5 NodeBGEEmbedding 产出（注意：不是单个 list[float]，是每个 chunk 的字典 → 避免 chunks 与 embedding 顺序对不上） ==============
    chunk_embeddings: dict[str, list[float]]  # key = chunk.chunk_id，value = 1024 维 BGE-M3 embedding

    # ============== N6 NodeImportMilvus 产出（持久化层） ==============
    milvus_collection: str              # 实际写入的集合名（通常 settings.milvus_collection）
    milvus_inserted_count: int          # Milvus 实际 upsert 条数（= chunks 数；失败时少）
    mongo_doc_id: str                   # Mongo documents_metadata 里的 doc_id（与 chunks.doc_id 一致）
    mongo_inserted_count: int           # Mongo chunks_metadata 实际 upsert 条数

    # ============== 通用：阶段日志 / 异常（用于写入 ingestion_tasks.failed_stage / failed_position） ==============
    stage_log: list[dict]               # 每个节点完成后追加：{"node": "node_entry", "ts": 173xxx, "ok": True, "note": "..."}
    last_error: str                     # 任意节点异常时：NodeBase 包装后写入（__str__），用于 failed_stage 写库
    last_failed_node: str               # 异常时：出错节点 name，下次 resume_from_stage 直接从这个节点开始



# =============================================
#  以下为 V1.1 梯队 0.1 新增：股票分析核心 Schema
#  对应：P0-1 规则-引用全局下标映射 / P0-2 6数字 clamp 修正 / P0-5 自动打标 outcome
# =============================================

DirectionT = Literal["bull", "bear", "neutral", "refused"]
ActionT = Literal["open_long", "open_short", "add_position", "reduce_position", "close_position", "hold", "standby"]


class ExpertRuleHit(TypedDict, total=False):
    """
    单条规则命中记录（对齐梯队 2.4 expert_rules.py）= 每位专家卡「🔍 为什么这么说？」popover 的唯一数据源。

    【P0-1 强制字段 supporting_source_idx】
    1) 在 score_per_expert 节点，记录的是「该专家本地 sources[0..N] 的下标」
    2) 在 generation 节点 sources 全局合并去重排序后 **必须重写** 为最终全局 sources[] 的下标
       —— 否则正文 [n] 点跳页会和「🔍」面板的 rule 指向跳错页
    3) postprocess 做一致性校验（sources 下标合法性，不合法的 idx 置为 -1，后处理对应 P0-6 引用兜底 ? chip）
    """
    rule_id: Required[str]               # 规则稳定 id，例如 FUND_01 / ANNOUNCE_01 / CAND_06
    rule_description: Required[str]      # 规则人类可读描述（pop-over 显示）
    category: Required[str]              # 7 大类之一：announce / fundamental / capital / psychology / risk / trend / candlestick
    points: Required[float]              # 本次命中给的分数（正数加分 / 负数减分；一票否决如 ANNOUNCE_01 = -999）
    is_veto: Required[bool]              # 是否为一票否决命中（True 时最终输出 refused 不给方向）
    confidence: Required[float]          # 命中置信度 0.0 ~ 1.0（例如 ROE 连续 3 年红灯 = 1.0；连续 1 年 = 0.6）
    supporting_source_idx: Required[list[int]]
    # ↑【P0-1 核心：全局 sources[] 最终下标】
    #   sources 全局合并去重排序后，generation 节点 postprocess 必须重写这里；
    #   前端「🔍 为什么？」点进来的每条 rule 后面 [1][2] 直接拿这里的 idx 去找对应的 source 跳页
    evidence_text_snippets: list[str]    # 命中时的关键原文片段（pop-over 直接显示，不用再点引用跳页也能看个大概）


class SourceCardItem(TypedDict):
    """
    前端「模块 6 引用卡」的单个来源条目，对应 sources[] 的一个元素。
    注意：doc_type / chunk_id 用于跳 PDF.js viewer 时拼 ?file=...&p=page_number；
         page_number < 0 时前端不显示「跳原书」按钮，只显示摘要片段。
    """
    source_global_idx: int               # 最终全局合并后的下标（1-based 展示给用户看的 [n] = source_global_idx + 1）
    doc_type: str                        # 归属哪本书/情报（例如 candlestick / news_capital_flow）
    display_name: str                    # 前端卡片标题：日本蜡烛图技术 / 东方财富公告 / 同花顺 7x24
    page_number: int                     # 对应原 PDF 页码（P.N）；<0 = 无页码（新闻/公告类）
    chunk_id: NotRequired[str]           # 对应 chunk_id（用于二次检索原文）
    pdf_name: NotRequired[str]           # doc/xxx.pdf 文件名（前端拼 PDF.js viewer 参数用）
    summary_text: str                    # 卡片摘要：该 source 对应的原文关键 1~2 句话（不是整段 display_text）
    thumbnail_url: NotRequired[str]      # 2x2 缩略图（如果 chunk 内有图，取第一张做缩略图）


class PerExpertResult(TypedDict):
    """
    梯队 2.5 score_per_expert 输出的每位专家独立结果 = 模块 3 专家发言卡的唯一数据源。

    【人格感 4 件套来源 —— 必须写入 state：】
    doc_type → expert_books 集合里的 color / emoji_tag / display_name / expert_role / fixed_mantra / weight 字段
    （梯队 3.3 合成时从 Mongo 拉取，写进前端 SSE 事件 expert_card_start payload）
    """
    doc_type: Required[str]              # 对齐 expert_books.doc_type；路由开关：如果 expert_books[doc_type].disabled=true → generation 直接跳过
    direction: Required[DirectionT]      # 该专家的独立判断（bull/bear/neutral）
    score: Required[float]               # 该专家的原始打分（-100 ~ +100），未乘 weight
    weighted_score: Required[float]      # score × expert_books.weight（最终加权用）
    reason_rules: Required[list[ExpertRuleHit]]
    # ↑ 该专家命中的所有规则 = 「🔍 为什么这么说？」pop-over 内容；
    #   注意：P0-1 强制 generation 节点必须把 supporting_source_idx 重写为全局合并后的下标
    spoken_opening: Required[str]        # 专家开场白（合成时带固定口头禅 System Prompt 硬约束，例如形态师：「我只看形态，不讲故事」）
    spoken_body: Required[str]            # 专家详细解释正文（Markdown，带 [1][2] 引用标号；标号 = supporting_source_idx + 1，1-based 展示）
    sources_local_raw: list[Chunk]       # 该专家本地召回 TopK 的原始 chunk（未合并去重；generation 节点全局合并用）


class FinalTradePlan(TypedDict):
    """
    梯队 3.3 generation 输出的仲裁官老李最终 6 数字交易计划 = 模块 4 金色边框表格的唯一数据源。

    【P0-2 强制 clamp 溢出修正：】
    position_shares_calc 与 position_percent_calc 是按 R/(入场-止损) 算出来的「理论值」；
    position_shares_final / position_percent_final 是经过以下规则强制 clamp 后的「实际执行值」：
      final = min( 理论仓位股数/百分比 , 用户画像 user_profile.single_ticket_max_percent=25% , 用户画像 single_industry_max_percent=30%（多只票时做行业集中度） )
    并且必须写 position_clamp_note（表格下方小字红色/金色提示）= 为什么被 clamp 了，例：
      「仓位已按您设置的单票 ≤25% 上限从 1000 股（160%） 调整为 156 股（15.6%）」
    如果没有 clamp 修正，则 clamp_note = ""。
    """
    direction: Required[DirectionT]      # 综合方向；若 ANNOUNCE_01/FUND_01 一票否决 → direction=refused 且表格里显示红色大警示条
    action: Required[ActionT]            # 动作：建仓/加仓/减仓/平仓/持有/观望
    entry_price: Required[float]         # 新进场条件：触发入场的价格（例如 1650；如果是减仓/平仓则填当前建议操作价）
    stop_loss_price: Required[float]     # 止损位：严格破位必须走（例如 1640；RISK_05 T+1 流动性修正后 1.3× 放宽的最终值）
    take_profit_price: Required[float]   # 止盈位：第一目标位（例如 1720；后续多级目标放 notes）
    position_shares_calc: Required[int]  # 【理论】按 R / (entry - stop) 反推的应该买多少股（未 clamp，可能超过账户本金或 25% 上限）
    position_percent_calc: Required[float]  # 【理论】占总账户百分比（0.0~1.0，未 clamp）
    position_shares_final: Required[int] # 【实际执行】P0-2 clamp 后的最终股数（100 股为单位向下取整，A 股一手）
    position_percent_final: Required[float]  # 【实际执行】clamp 后的百分比
    r_multiplier: Required[float]        # R 倍数 = |(take_profit - entry) / (entry - stop_loss)|；例如 2.4 显示为 R/R 1:2.4
    expiry_condition: Required[str]      # 失效条件：例如「持有 ≤ 10 个交易日未触发止盈 → 无条件离场；跌破 20 日线无条件离场」
    position_clamp_note: Required[str]   # 【P0-2 强制】clamp 溢出修正的小字说明；未修正则为空字符串
    extra_notes: list[str]               # 补充小字：多级目标 / T+1 流动性放宽提醒 / 交易成本 0.5% 扣除提醒等


class AnalysisSnapshot(TypedDict):
    """
    梯队 3.5 每次问答结束后写库的完整快照 = 长期自学习闭环 D6 双保险的唯一事实源。

    【P0-5 自动打标闭环（V4-4 每天 cron 跑）】
    1) 每天 cron：筛选 created_at ≥ 20 个交易日之前 AND verified_outcome is None 的快照
    2) 去东财免费接口 / Tushare 拉 target_stock_code 在 20 个交易日后的复权收盘价 close_after
    3) 自动打标：
       correct   = (direction=='bull'   and close_after > entry_price * 1.01)
                 or (direction=='bear'   and close_after < entry_price * 0.99)
                 or (direction=='refused' and close_after 期间 maxdrawdown > 15%)  →  拒答对了，躲过坑
       wrong     = 其他情况
       neutral   = 还不到 20 天（不打标）
    4) 打标完成 → 回灌 expert_books[].historical_accuracy → 调整 weight（<45% 自动 disable）
    """
    snapshot_id: Required[str]           # UUID，主键
    user_id: Required[str]               # 匿名 UUID（对齐 user_profiles._id；不需要登录）
    target_stock_code: Required[str]     # 6 位 A 股代码 / ETF 代码（600519 / 510300）
    target_stock_name: Required[str]     # 名称（冗余，方便列表展示）
    user_original_query: Required[str]   # 用户原问题（完整文字，不脱敏）
    is_hypothetical_override: Required[bool]  # 是否为「假设模式追问」（= P0-8：检测到如果/假如...直接覆写规则字段，不重走 Milvus）
    created_at: Required[float]          # 时间戳 seconds（注意：自动打标 cron 要按 20 个「交易日」算，不是自然日，要跳过周末节假日）
    final_direction: Required[DirectionT]
    final_trade_plan: Required[FinalTradePlan]
    per_expert_results: list[PerExpertResult]  # 当时每位专家的结果
    sources_global_final: list[SourceCardItem] # 当时全局合并后的 sources（方便历史记录 Modal 重新渲染引用卡）
    user_profile_snapshot: Required[dict]      # 当时用户画像 3 字段 + 持仓快照的 JSON（防止后来改了画像回测算不准）
    verified_outcome: NotRequired[str]         # P0-5 打标用：correct / wrong / neutral / refused_correct（躲过坑也算对）/ None
    verified_close_after: NotRequired[float]   # 20 交易日后的复权收盘价
    verified_at: NotRequired[float]            # 打标时间戳
    manual_outcome_override: NotRequired[str]  # 用户手动点「当时判断对了」的人工覆盖（优先于自动打标）


class StructuredInput(TypedDict, total=False):
    """
    梯队 2.3 extract_features + 2.4 expert_rules.score() 的输入结构化中间结果 = 所有打分规则的唯一判断数据源。

    【P0-8 假设模式追问：】
    detect_hypothetical_modifiers 命中「如果/假如/假设...」+ 字段关键词 → 直接覆写这里对应的字段（例如 support_levels[0] = 1600），
    再调用 2.4 score() 重新打分，不走 2.1 Milvus 重新检索（5× 快）
    """
    stock_code: Required[str]
    stock_name: Required[str]
    industry_sw_l1: Required[str]        # 申万一级行业（stock_dict.industry() 返回；用于 RISK_04 行业集中度检查）
    list_days: Required[int]             # 上市天数（stock_dict.is_new_stock()；<60 天 → 合规围栏直接拒答）
    is_st_or_special: Required[bool]     # 是否 ST/*ST/退市整理 → 合规围栏直接拒答

    last_close: Required[float]          # T-1 或 T 实时收盘价（东财免费接口拉）
    change_pct_today: Required[float]    # 今日涨跌幅 %（正负）
    volume_ratio_today: Required[float]  # 量比（东财 push2 免费接口有）
    turnover_rate_today: Required[float] # 换手率 %

    support_levels: list[float]          # 关键支撑位列表（从低到高排序；例如 [1600, 1640]）
    resistance_levels: list[float]       # 关键压力位列表（从低到高；例如 [1700, 1760]）
    chart_features: list[str]            # 形态识别关键词：黄昏之星 / 启明星 / 头肩顶 / 箱体突破 / 放量破位 等（来自 VL 读图 + LLM 结构化提取）
    trend_50d: Required[DirectionT]      # 50 日均线方向：bull（在均线上方）/ bear / neutral
    trend_200d: Required[DirectionT]     # 200 日均线方向：长期牛熊判断

    roe_ttm: Required[float]             # 扣非 ROE TTM（东财 F10 免费接口；连续 3 年 < 8% → FUND_01 ROE 红灯 -5）
    debt_ratio: Required[float]          # 资产负债率 %（>70% 重资产行业 FUND_02 扣分）
    op_cf_yoy: Required[float]           # 经营现金流同比 %（负 → FUND_02 扣分）
    eps_consensus_yoy: Required[float]   # 一致预期 EPS 同比（没有则填 0；FUND_03）
    target_price_consensus: Required[float]  # 一致预期目标价（没有则填 0）

    north_net_inflow_5d: Required[float]    # 北向 5 日累计净流入 亿元（没有则填 0；CAPITAL_01）
    margin_net_buy_5d: Required[float]      # 融资余额 5 日净买入 亿元（没有则填 0；CAPITAL_02）
    dragon_tiger_net_buy_today: Required[float]  # 今日龙虎榜净买入 亿元（没有则填 0；CAPITAL_03）

    news_neg_count_7d: Required[int]     # 近 7 天利空新闻条数（公告关键词：拟减持/立案/业绩预亏/非标/监管函 → ANNOUNCE_01 熔断）
    news_pos_count_7d: Required[int]     # 近 7 天利好条数（股权激励/回购/业绩预增/重大合同 → ANNOUNCE_02 加分）
    news_keywords: list[str]             # 近 7 天新闻关键词（用于情报师发言摘要）

    user_account_capital: Required[float]    # 用户画像：总账户本金（元）
    user_risk_r_pct: Required[float]         # 用户画像：单笔 R = 1%/2%/3%（默认 1%）
    user_single_ticket_max: Required[float]  # 用户画像：单票最大仓位 %（默认 25%，P0-2 clamp 用）
    user_industry_max: Required[float]       # 用户画像：单行业最大总仓位 %（默认 30%，RISK_04）
    user_current_positions: Required[list[dict]]  # 用户当前持仓列表 [{code,name,percent,cost}]（用于行业集中度/总仓位限制）

