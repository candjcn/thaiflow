 AI Commerce Platform Architecture Proposal

  ReelSpeak — 商业化基础设施架构设计

  版本: v1.0 | 日期: 2026-07-16 | 状态: 设计稿

  ---
  目录

  1. #1-总体架构图
  2. #2-七大模块职责
  3. #3-模块依赖关系
  4. #4-数据流
  5. #5-credits-生命周期
  6. #6-一次-ai-调用的完整流程
  7. #7-provider-与-billing-完全解耦
  8. #8-支持未来新增-provider
  9. #9-支持未来新增-capability
  10. #10-支持未来新增收费策略
  11. #11-支持未来新增会员套餐
  12. #12-风险分析
  13. #13-推荐实施顺序

  ---
  1. 总体架构图

  ┌─────────────────────────────────────────────────────────────────────┐
  │                         USER (Browser / App)                        │
  └─────────────────────────────┬───────────────────────────────────────┘
                                │  HTTP Request
                                ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                      EXPERIENCE LAYER (Flask app.py)                │
  │           /api/transcribe  /api/translate  /api/tts  ...            │
  └──────────────────────────────┬──────────────────────────────────────┘
                                 │ resolve user → capability
                                 ▼
            ┌────────────────────────────────────┐
            │           ① IDENTITY               │
            │   User · Profile · LoginProvider   │
            │   Language · Timezone · Status     │
            └────────────────┬───────────────────┘
                             │ user_id, plan
                             ▼
            ┌────────────────────────────────────┐
            │         ⑦ PERMISSION ENGINE        │
            │  CanTranscribe · CanTranslate      │
            │  CanTTS · CanPronunciation         │
            │  CanExport · CanShadowing ...      │
            └────────────────┬───────────────────┘
                             │ permission granted
                             ▼
            ┌────────────────────────────────────┐
            │         ④ PRICING ENGINE           │
            │  Capability → Cost Estimate        │
            │  → Credits Required                │
            └────────────────┬───────────────────┘
                             │ credits_required
                             ▼
            ┌────────────────────────────────────┐
            │            ③ WALLET                │
            │  GiftCredits · PaidCredits         │
            │  SubscriptionCredits · Balance     │
            │  Reserve() → lock credits          │
            └────────────────┬───────────────────┘
                             │ reservation_id
                             ▼
            ┌────────────────────────────────────┐
            │           ① AI ROUTER              │
            │  Capability + Quality + Plan       │
            │  + Health + Cost + Latency         │
            │     → select Provider              │
            └────────────────┬───────────────────┘
                             │ provider_id, model
                             ▼
     ┌───────────────────────────────────────────────────┐
     │              PROVIDER LAYER (existing)            │
     │  Groq · OpenAI · Azure · Gemini · DeepSeek       │                                                                                                          
     │  Youdao · Cloudflare · (future: ...)              │                                                                                                         
     └───────────────────────────┬───────────────────────┘                                                                                                           
                                 │ response + actual_cost                                                                                                          
                                 ▼                                                                                                                                   
            ┌────────────────────────────────────┐                                                                                                                 
            │         ④ PRICING ENGINE           │                                                                                                                   
            │  actual_cost → actual_credits      │                                                                                                                 
            │  (settle reservation)              │                                                                                                                   
            └────────────────┬───────────────────┘                                                                                                                   
                             │ actual_credits                                                                                                                      
                             ▼                                                                                                                                       
            ┌────────────────────────────────────┐                                                                                                                   
            │            ③ WALLET                │
            │  Settle(reservation_id,            │                                                                                                                   
            │          actual_credits)           │                                                                                                                 
            └────────────────┬───────────────────┘                                                                                                                   
                             │ settled                                                                                                                             
                             ▼                                                                                                                                       
            ┌────────────────────────────────────┐                                                                                                                 
            │          ⑤ USAGE LOG               │                                                                                                                   
            │  user · capability · provider      │                                                                                                                   
            │  cost · credits · latency          │
            │  request_id · status               │                                                                                                                   
            └────────────────┬───────────────────┘                                                                                                                 
                             │ logged                                                                                                                                
                             ▼                                                                                                                                     
  ┌─────────────────────────────────────────────────────────────────────┐                                                                                            
  │                    RESPONSE → User                                  │                                                                                          
  └─────────────────────────────────────────────────────────────────────┘                                                                                            
                                                                                                                                                                   
            ┌────────────────────────────────────┐                                                                                                                 
            │         ⑥ SUBSCRIPTION             │                                                                                                                   
            │  Free · Plus · Pro · Enterprise    │                                                                                                                   
            │  定义每个套餐拥有的：              │                                                                                                                   
            │  Capabilities · Credits · Perms    │                                                                                                                   
            └────────────────────────────────────┘                                                                                                                 
            （Subscription 在用户登录 / 续期时写入                                                                                                                   
              Identity & Permission，不参与实时调用链）                                                                                                              
                                                                                                                                                                     
  ---                                                                                                                                                                
  2. 七大模块职责                                                                                                                                                    
                                                                                                                                                                     
  ① AI Router                                                                                                                                                        
                                                                                                                                                                     
  一句话定义：业务代码告诉 Router "我需要什么能力"，Router 决定"谁来做"。                                                                                            
                                                                                                                                                                   
  职责：                                                                                                                                                           
    接受 Capability Request（能力请求），返回 ProviderHandle（提供商句柄）                                                                                           
         
  输入参数：                                                                                                                                                         
    - capability      : CapabilityType  # transcription / translation / tts / ...                                                                                  
    - quality_tier    : QualityTier     # economy / standard / premium                                                                                               
    - user_plan       : PlanTier        # free / plus / pro / enterprise                                                                                           
    - input_metadata  : dict            # 语言、时长、字符数等（用于估算成本）                                                                                       
                                                                                                                                                                     
  内部决策因子：                                                                                                                                                     
    - Provider Health Score（实时心跳 / 错误率）                                                                                                                     
    - Provider Latency（移动平均 P50/P95）                                                                                                                           
    - Provider Cost（当前单价 × 估算用量）                                                                                                                         
    - Plan Constraint（套餐允许哪些 Provider）                                                                                                                       
    - Quality Constraint（Economy 不能用 premium-only Provider）                                                                                                     
                                                                                                                                                                     
  输出：                                                                                                                                                             
    - ProviderHandle { provider_id, model_id, endpoint, timeout }                                                                                                    
                                                                                                                                                                     
  能力：                                                                                                                                                             
    - Fallback Chain        : primary → secondary → tertiary                                                                                                         
    - Health Check          : 后台定时 ping，异常时自动降级                                                                                                          
    - Retry with Backoff    : 同一 Provider 超时自动重试                                                                                                           
    - Cost Circuit Breaker  : 实时成本超阈值自动停止                                                                                                                 
    - Dry Run Mode          : 返回选择结果但不实际调用（测试用）                                                                                                     
                                                                                                                                                                     
  与现有代码的关系：                                                                                                                                                 
  现有 backend/config/providers.py 已经按服务商分组管理 API Key，AI Router 是在此之上增加一个决策层，不修改 providers.py 的配置结构。                                
                                                                                                                                                                     
  ---                                                                                                                                                                
  ② Identity                                                                                                                                                         
                                                                                                                                                                     
  一句话定义：系统里"谁在使用"的唯一事实来源。                                                                                                                     
                                                                                                                                                                     
  核心实体：                                                                                                                                                       
                                                                                                                                                                   
  User:                                                                                                                                                              
    - user_id          : UUID            # 系统内部 ID，永不变                                                                                                     
    - email            : str (optional)                                                                                                                              
    - status           : UserStatus      # active / suspended / deleted                                                                                            
    - created_at       : datetime                                                                                                                                    
    - current_plan     : PlanTier        # 冗余存储，方便快速读取                                                                                                    
                                                                                                                                                                     
  Profile:                                                                                                                                                           
    - display_name     : str                                                                                                                                         
    - avatar_url       : str                                                                                                                                         
    - preferred_lang   : LanguageCode    # 学习目标语言                                                                                                              
    - ui_lang          : LanguageCode    # 界面语言（已有 i18n 6语言）                                                                                               
    - timezone         : str                                                                                                                                       
                                                                                                                                                                   
  Identity (Login Binding):                                                                                                                                          
    - user_id          : UUID                                                                                                                                        
    - provider         : LoginProvider   # wechat / apple / google / email                                                                                           
    - provider_uid     : str             # 第三方 UID                                                                                                                
    - linked_at        : datetime                                                                                                                                    
                                                                                                                                                                   
  本阶段不实现：                                                                                                                                                     
    - 登录流程                                                                                                                                                       
    - Session 管理                                                                                                                                                   
    - OAuth 回调                                                                                                                                                     
    只设计数据结构和接口契约。                                                                                                                                     
                                                                                                                                                                     
  ---                                                                                                                                                              
  ③ Wallet                                                                                                                                                         
                                                                                                                                                                     
  一句话定义：用户所有 Credits 的统一账本。
                                                                                                                                                                     
  Credits 类型（优先级顺序消费）：                                                                                                                                 
    1. SubscriptionCredits  # 套餐每月赠送，月末清零                                                                                                               
    2. GiftCredits          # 运营赠送，有过期时间                                                                                                                   
    3. PaidCredits          # 用户购买，永不过期                                                                                                                   
                                                                                                                                                                     
  Wallet:                                                                                                                                                            
    - wallet_id                : UUID                                                                                                                                
    - user_id                  : UUID                                                                                                                                
    - subscription_credits     : int      # 当月剩余                                                                                                                 
    - subscription_expires_at  : datetime # 下次重置时间                                                                                                             
    - gift_credits             : int      # 所有未过期 Gift Credits 之和                                                                                             
    - paid_credits             : int                                                                                                                               
    - total_balance            : int      # 三者之和（computed）                                                                                                     
    - version                  : int      # 乐观锁，防并发扣款双重消费                                                                                               
                                                                                                                                                                     
  核心方法：                                                                                                                                                         
                                                                                                                                                                     
    Reserve(user_id, amount) → reservation_id | InsufficientFunds                                                                                                    
      # 预扣款，锁定 credits，防止并发问题                                                                                                                           
      # 消费顺序：Subscription → Gift → Paid                                                                                                                         
                                                                                                                                                                     
    Settle(reservation_id, actual_amount) → void                                                                                                                   
      # 实际 AI 调用完成后，用真实金额结算                                                                                                                           
      # actual_amount <= reserved_amount（退还差额）                                                                                                                 
      # actual_amount > reserved_amount（自动补扣，若不足则记录欠款）                                                                                                
                                                                                                                                                                     
    Release(reservation_id) → void                                                                                                                                   
      # AI 调用失败时全额释放预扣                                                                                                                                    
                                                                                                                                                                     
    Add(user_id, amount, type, source, expires_at) → void                                                                                                            
      # 充值：购买 / 运营赠送 / 套餐发放                                                                                                                             
                                                                                                                                                                     
    Refund(usage_log_id, amount, reason) → void                                                                                                                      
      # 退款，写入 GiftCredits（不退原路，方便运营控制）                                                                                                             
                                                                                                                                                                     
    History(user_id, page) → [WalletTransaction]                                                                                                                   
      # 流水记录                                                                                                                                                     
                                                                                                                                                                     
  WalletTransaction:                                                                                                                                                 
    - tx_id         : UUID                                                                                                                                           
    - wallet_id     : UUID                                                                                                                                           
    - type          : TxType      # reserve / settle / release / add / refund                                                                                      
    - amount        : int         # 正 = 入账，负 = 扣除                                                                                                           
    - credit_type   : CreditType  # subscription / gift / paid                                                                                                     
    - ref_id        : UUID        # usage_log_id 或 订单 ID                                                                                                          
    - created_at    : datetime                                                                                                                                     
    - note          : str                                                                                                                                            
                                                                                                                                                                     
  ---                                                                                                                                                                
  ④ Pricing Engine                                                                                                                                                   
                                                                                                                                                                     
  一句话定义：把"Provider 实际消耗"转换成"用户被扣多少 Credits"。
                                                                                                                                                                     
  Pricing Engine 只认识 Capability，不认识 Provider。                                                                                                              
                                                                                                                                                                   
  三层结构：                                                                                                                                                         
                                                                                                                                                                     
  Layer 1 — Provider Cost Table（后台维护）                                                                                                                          
    记录每个 Provider × Model × 计费维度 的真实 API 单价                                                                                                             
                                                                                                                                                                     
    ProviderCostEntry:                                                                                                                                               
      - provider_id   : str          # groq / azure / gemini / deepseek                                                                                              
      - model_id      : str          # whisper-large-v3 / gemini-flash-lite                                                                                          
      - capability    : str          # transcription / translation / tts                                                                                             
      - unit          : CostUnit     # per_minute / per_1k_chars / per_1k_tokens                                                                                     
      - unit_price    : Decimal      # USD，精确到 10 位小数                                                                                                         
      - updated_at    : datetime                                                                                                                                     
                                                                                                                                                                     
  Layer 2 — Pricing Policy（运营维护）                                                                                                                               
    定义 Capability × QualityTier × PlanTier 的 Credits 定价                                                                                                         
                                                                                                                                                                     
    PricingPolicy:                                                                                                                                                   
      - policy_id       : UUID                                                                                                                                     
      - capability      : CapabilityType                                                                                                                             
      - quality_tier    : QualityTier    # economy / standard / premium                                                                                            
      - plan_tier       : PlanTier       # free / plus / pro / enterprise                                                                                            
      - formula         : FormulaType    # fixed / cost_multiplier / tiered                                                                                        
      - multiplier      : Decimal        # 例如 cost_multiplier = 3.0（毛利 200%）                                                                                 
      - fixed_amount    : int            # formula=fixed 时使用                                                                                                      
      - min_credits     : int            # 最低扣费                                                                                                                
      - max_credits     : int            # 封顶扣费                                                                                                                  
      - effective_from  : datetime                                                                                                                                   
      - effective_to    : datetime       # 支持限时促销                                                                                                              
                                                                                                                                                                     
  Layer 3 — Pricing Engine（运行时）                                                                                                                                 
    Estimate(capability, quality_tier, plan_tier, input_metadata) → credits_estimate                                                                               
      # 调用前估算，用于 Reserve()                                                                                                                                   
                                                                                                                                                                   
    Calculate(capability, quality_tier, plan_tier, actual_usage) → credits_actual                                                                                    
      # AI 返回实际用量后精确计算，用于 Settle()                                                                                                                     
                                                                                                                                                                     
    # actual_usage 示例：                                                                                                                                            
    #   transcription: { duration_seconds: 142 }                                                                                                                     
    #   translation:   { char_count: 3200 }                                                                                                                          
    #   tts:           { char_count: 480, voice_tier: "neural" }                                                                                                   
    #   pronunciation: { duration_seconds: 8 }                                                                                                                       
                                                                                                                                                                     
  数据隔离原则：                                                                                                                                                     
    - Layer 1（Cost Table）= 运营内部数据，用于成本核算，用户不可见                                                                                                  
    - Layer 2（Policy）= 运营配置，决定用户看到的 Credits 价格                                                                                                       
    - Layer 3（Engine）= 纯计算逻辑，无状态，可单元测试                                                                                                              
                                                                                                                                                                   
  ---                                                                                                                                                                
  ⑤ Usage Log                                                                                                                                                        
                                                                                                                                                                     
  一句话定义：每一次 AI 调用的完整事实记录，是退款、统计、客服的唯一依据。                                                                                           
                                                                                                                                                                     
  UsageLog:                                                                                                                                                        
    - log_id          : UUID            # 全局唯一，贯穿整个调用链                                                                                                 
    - user_id         : UUID                                                                                                                                         
    - session_id      : str             # 用户的播放 session（可选）                                                                                               
    - capability      : CapabilityType  # transcription / translation / tts                                                                                          
    - quality_tier    : QualityTier                                                                                                                                  
    - provider_id     : str             # 实际使用的 Provider                                                                                                        
    - model_id        : str             # 实际使用的 Model                                                                                                           
    - plan_tier       : PlanTier        # 调用时用户的套餐                                                                                                           
                                                                                                                                                                     
    # 用量原始数据                                                                                                                                                   
    - input_units     : Decimal         # 分钟数 / 字符数 / Token 数                                                                                               
    - input_unit_type : CostUnit                                                                                                                                     
                                                                                                                                                                     
    # 成本                                                                                                                                                           
    - provider_cost_usd : Decimal       # 真实 API 成本（USD）                                                                                                       
    - credits_reserved  : int           # 预扣                                                                                                                       
    - credits_charged   : int           # 实扣                                                                                                                       
    - credits_refunded  : int           # 退款（如果有）                                                                                                             
                                                                                                                                                                     
    # 技术指标                                                                                                                                                     
    - latency_ms      : int                                                                                                                                          
    - status          : LogStatus       # success / failed / refunded / timeout                                                                                    
    - error_code      : str (optional)                                                                                                                               
    - retry_count     : int                                                                                                                                        
    - fallback_used   : bool                                                                                                                                         
    - fallback_from   : str             # 如果发生了 Fallback，记录原 Provider                                                                                       
                                                                                                                                                                   
    # 时间                                                                                                                                                           
    - requested_at    : datetime                                                                                                                                   
    - completed_at    : datetime                                                                                                                                     
                                                                                                                                                                   
    # 关联                                                                                                                                                           
    - reservation_id  : UUID            # Wallet 预扣 ID                                                                                                             
    - request_id      : str             # HTTP 请求 ID（方便串联日志）
                                                                                                                                                                     
  用途：                                                                                                                                                           
    - 运营统计：按 Capability / Provider / Plan 分析用量和成本                                                                                                       
    - 退款依据：Refund(usage_log_id) 精确追溯                                                                                                                        
    - 客服工具：通过 log_id 还原任何一次调用的完整经过                                                                                                               
    - 异常检测：Fallback 率、失败率、高延迟告警                                                                                                                      
    - 成本归因：Provider Cost × 用量 = 每日成本报表                                                                                                                  
                                                                                                                                                                     
  与现有代码的关系：                                                                                                                                                 
    现有 USAGE_LOG = videos/usage_log.jsonl 是简单的 JSONL 文件。                                                                                                    
    新 Usage Log 是结构化数据库记录，但可以保持 JSONL 作为短期备份。                                                                                                 
                                                                                                                                                                     
  ---                                                                                                                                                                
  ⑥ Subscription                                                                                                                                                     
                                                                                                                                                                     
  一句话定义：定义每个套餐"能做什么、有多少 Credits"，在用户开通/续期时写入系统。                                                                                    
                                                                                                                                                                     
  套餐定义（运营可配置）：                                                                                                                                         
                                                                                                                                                                   
    Plan: Free                                                                                                                                                       
      monthly_credits       : 100                                                                                                                                  
      capabilities          : [transcription_economy, translation_economy]                                                                                           
      permissions           : [CanTranscribe, CanTranslate]                                                                                                          
      quality_tiers_allowed : [economy]                                                                                                                            
      max_file_duration_min : 5                                                                                                                                      
      provider_pool         : [groq, deepseek]   # 只能用低成本 Provider                                                                                             
                                                                                                                                                                     
    Plan: Plus                                                                                                                                                       
      monthly_credits       : 1,000                                                                                                                                  
      capabilities          : [transcription, translation, tts, romanize]                                                                                            
      permissions           : [CanTranscribe, CanTranslate, CanTTS,                                                                                                  
                               CanRomanize, CanExport]                                                                                                               
      quality_tiers_allowed : [economy, standard]                                                                                                                    
      max_file_duration_min : 30                                                                                                                                   
      provider_pool         : [groq, gemini, deepseek, azure]                                                                                                        
                                                                                                                                                                   
    Plan: Pro                                                                                                                                                        
      monthly_credits       : 5,000                                                                                                                                  
      capabilities          : [ALL]
      permissions           : [ALL]                                                                                                                                  
      quality_tiers_allowed : [economy, standard, premium]                                                                                                         
      max_file_duration_min : 120                                                                                                                                  
      provider_pool         : [ALL]                                                                                                                                  
         
    Plan: Enterprise                                                                                                                                                 
      monthly_credits       : custom                                                                                                                               
      capabilities          : custom
      permissions           : custom                                                                                                                               
      quality_tiers_allowed : [ALL]                                                                                                                                
      max_file_duration_min : unlimited                                                                                                                              
      provider_pool         : [ALL + dedicated]
                                                                                                                                                                     
  数据结构：                                                                                                                                                       
                                                                                                                                                                   
    UserSubscription:                                                                                                                                                
      - sub_id          : UUID
      - user_id         : UUID                                                                                                                                       
      - plan_tier       : PlanTier                                                                                                                                 
      - status          : SubStatus   # active / expired / cancelled                                                                                               
      - started_at      : datetime                                                                                                                                   
      - expires_at      : datetime                                                                                                                                 
      - auto_renew      : bool                                                                                                                                       
      - payment_method  : str         # 本阶段为空，支付阶段填充                                                                                                     
      - credits_quota   : int         # 本期配额
      - credits_reset_at: datetime    # 下次重置时间                                                                                                                 
                                                                                                                                                                   
    PlanDefinition（运营表）:                                                                                                                                        
      - plan_id         : str                                                                                                                                        
      - display_name    : str         # "Plus 会员"                                                                                                                  
      - monthly_price   : Decimal     # 本阶段为 0，支付阶段填充                                                                                                     
      - monthly_credits : int                                                                                                                                      
      - features        : json        # 上方所有字段                                                                                                                 
      - effective_from  : datetime                                                                                                                                   
                                                                                                                                                                     
  订阅事件（写入 Event Bus）:                                                                                                                                        
    - SubscriptionActivated   → Wallet.Add(subscription_credits)                                                                                                     
    - SubscriptionRenewed     → Wallet.Reset(subscription_credits)                                                                                                 
    - SubscriptionExpired     → Permission.Downgrade(user_id, Free)                                                                                                  
    - SubscriptionCancelled   → Permission.ScheduleDowngrade()                                                                                                     
                                                                                                                                                                     
  ---                                                                                                                                                                
  ⑦ Permission Engine                                                                                                                                                
                                                                                                                                                                     
  一句话定义：把"用户能做什么"变成一组命名的布尔值，消除代码中所有 if VIP 判断。                                                                                   
                                                                                                                                                                     
  权限定义（CapabilityPermission 枚举）：                                                                                                                          
                                                                                                                                                                   
    语言学习核心功能：                                                                                                                                               
      CanTranscribe              # ASR 识别                                                                                                                        
      CanTranslate               # 翻译                                                                                                                              
      CanTTS                     # 生成 TTS 课程                                                                                                                   
      CanPronunciationAssess     # 发音评分                                                                                                                          
      CanRomanize                # 拼音 / 罗马拼音                                                                                                                   
      CanWordDefine              # 单词释义                                                                                                                        
      CanShadowing               # 影子跟读                                                                                                                          
      CanExport                  # 导出 SRT / 视频                                                                                                                   
                                                                                                                                                                     
    质量控制：                                                                                                                                                       
      CanUseStandardQuality      # Standard Provider（中等质量）                                                                                                     
      CanUsePremiumQuality       # Premium Provider（最高质量）                                                                                                      
                                                                                                                                                                     
    用量控制：                                                                                                                                                       
      CanProcessLongVideo        # 视频 > 5 分钟                                                                                                                     
      CanBatchProcess            # 批量处理                                                                                                                        
      CanPriorityQueue           # 优先队列                                                                                                                          
                                                                                                                                                                   
  Permission Engine API:                                                                                                                                             
                                                                                                                                                                   
    Check(user_id, permission) → bool                                                                                                                                
      # 实时检查，结果可缓存 60s                                                                                                                                   
                                                                                                                                                                     
    CheckAll(user_id, permissions[]) → dict[permission, bool]                                                                                                        
      # 批量检查（减少网络往返）                                                                                                                                   
                                                                                                                                                                     
    Grant(user_id, permission, expires_at) → void                                                                                                                  
      # 运营手动授权（VIP 礼包等）                                                                                                                                   
                                                                                                                                                                     
    Revoke(user_id, permission) → void                                                                                                                             
      # 撤销权限                                                                                                                                                     
                                                                                                                                                                     
    GetUserPermissions(user_id) → PermissionSet                                                                                                                    
      # 返回用户完整权限集合                                                                                                                                         
                                                                                                                                                                     
  权限来源（优先级从高到低）：                                                                                                                                     
    1. ManualGrant     # 运营手动授权（最高优先级，可覆盖套餐）                                                                                                      
    2. Subscription    # 套餐权限                                                                                                                                    
    3. Default         # 免费用户默认权限                                                                                                                          
                                                                                                                                                                     
  实现方式：                                                                                                                                                         
    - Permission 计算结果存入缓存（Redis / 内存）                                                                                                                  
    - Subscription 变更时主动 invalidate 缓存                                                                                                                        
    - 缓存 miss 时从 UserSubscription + PlanDefinition 重新计算                                                                                                    
                                                                                                                                                                     
  ---                                                                                                                                                                
  3. 模块依赖关系                                                                                                                                                    
                                                                                                                                                                     
  ┌──────────────┐                                                                                                                                                   
                      │  Subscription │                                                                                                                              
                      └──────┬───────┘                                                                                                                               
                             │ 激活/续期时写入                                                                                                                     
                      ┌──────▼───────┐        ┌──────────────┐                                                                                                       
                      │   Identity   │◄───────►│  Permission  │                                                                                                    
                      └──────┬───────┘        └──────┬───────┘                                                                                                       
                             │ user_id, plan          │ permission_set                                                                                               
                             │                        │                                                                                                              
                      ┌──────▼────────────────────────▼──────┐                                                                                                       
                      │          Experience Layer             │                                                                                                      
                      │          (Flask app.py)               │                                                                                                      
                      └──────┬───────────────────────────────┘                                                                                                     
                             │                                                                                                                                       
                ┌────────────▼────────────┐                                                                                                                          
                │      Pricing Engine     │                                                                                                                          
                │  (estimate → credits)   │                                                                                                                          
                └────────────┬────────────┘                                                                                                                        
                             │                                                                                                                                       
                ┌────────────▼────────────┐                                                                                                                          
                │         Wallet          │
                │      (Reserve)          │                                                                                                                          
                └────────────┬────────────┘                                                                                                                        
                             │                                                                                                                                       
                ┌────────────▼────────────┐                                                                                                                        
                │        AI Router        │                                                                                                                          
                └────────────┬────────────┘                                                                                                                        
                             │                                                                                                                                       
                ┌────────────▼────────────┐                                                                                                                        
                │    Provider Layer       │                                                                                                                          
                └────────────┬────────────┘
                             │                                                                                                                                       
                ┌────────────▼────────────┐                                                                                                                        
                │     Pricing Engine      │                                                                                                                          
                │     (settle → actual)   │
                └────────────┬────────────┘                                                                                                                          
                             │                                                                                                                                     
                ┌────────────▼────────────┐                                                                                                                        
                │         Wallet          │                                                                                                                          
                │         (Settle)        │
                └────────────┬────────────┘                                                                                                                          
                             │                                                                                                                                     
                ┌────────────▼────────────┐                                                                                                                          
                │        Usage Log        │
                └─────────────────────────┘                                                                                                                          
                                                                                                                                                                   
  依赖规则（单向，禁止循环）：                                                                                                                                       
                                                                                                                                                                   
    Experience     → Identity, Permission, Pricing, Wallet, Router, UsageLog                                                                                         
    Permission     → Identity, Subscription                                                                                                                          
    Wallet         → （纯账本，不依赖任何业务模块）                                                                                                                
    Pricing Engine → Provider Cost Table, Pricing Policy                                                                                                             
                     （不依赖 Provider 实现，只依赖其 cost metadata）                                                                                              
    AI Router      → Provider Layer, Provider Health（内部状态）                                                                                                     
    Usage Log      → （纯写入，不依赖其他模块）                                                                                                                      
    Subscription   → Identity, Wallet, Permission                                                                                                                    
                                                                                                                                                                     
  禁止的依赖：                                                                                                                                                       
    Provider Layer → Billing（任何方向）                                                                                                                             
    Wallet         → Provider Layer                                                                                                                                  
    Usage Log      → Wallet（只被 Wallet 关联，不主动调用）                                                                                                        
                                                                                                                                                                     
  ---                                                                                                                                                                
  4. 数据流                                                                                                                                                          
                                                                                                                                                                     
  4.1 正常调用数据流                                                                                                                                                 
                                                                                                                                                                     
  User Request                                                                                                                                                     
    │                                                                                                                                                              
    │ {file, capability="transcription", quality="standard"}                                                                                                         
    ▼    
  Experience Layer                                                                                                                                                   
    │ 1. 解析 JWT → user_id                                                                                                                                        
    │ 2. 调用 Permission.Check(user_id, CanTranscribe)                                                                                                               
    │ 3. 调用 Permission.Check(user_id, CanUseStandardQuality)                                                                                                     
    │                                                                                                                                                                
    ├─ [权限拒绝] → 403 + 提示升级套餐                                                                                                                               
    │                                                                                                                                                                
    │ [权限通过]                                                                                                                                                     
    │ 4. 从 file 提取 input_metadata {duration_seconds: 142}                                                                                                         
    ▼                                                                                                                                                                
  Pricing Engine.Estimate(                                                                                                                                         
    capability="transcription",                                                                                                                                      
    quality="standard",                                                                                                                                              
    plan="plus",                                                                                                                                                     
    input={duration_seconds: 142}                                                                                                                                    
  ) → credits_estimate = 14                                                                                                                                          
    │                                                                                                                                                              
    ▼                                                                                                                                                                
  Wallet.Reserve(user_id, amount=14)                                                                                                                               
    │ 检查余额 → balance=350 ≥ 14 ✓                                                                                                                                  
    │ 扣除预扣：balance=336, reserved=14                                                                                                                             
    │ → reservation_id = "rsv_abc123"                                                                                                                              
    │                                                                                                                                                                
    ├─ [余额不足] → 释放，返回 402 + 充值提示                                                                                                                        
    │                                                                                                                                                                
    ▼                                                                                                                                                                
  AI Router.Route(                                                                                                                                                   
    capability="transcription",                                                                                                                                      
    quality="standard",                                                                                                                                            
    plan="plus",                                                                                                                                                     
    input_metadata={duration_seconds: 142}                                                                                                                         
  )
    │ Health Check: groq=✓(P50=1.2s), azure=✓(P50=3.4s)                                                                                                            
    │ Cost: groq=$0.0001/min, azure=$0.0004/min → groq cheaper                                                                                                     
    │ → ProviderHandle{provider="groq", model="whisper-large-v3"}                                                                                                    
    │                                                                                                                                                              
    ▼                                                                                                                                                                
  Provider Layer (Groq Whisper)                                                                                                                                      
    │ 实际调用，耗时 8.3s                                                                                                                                            
    │ → {text: "...", actual_duration: 142.3s}                                                                                                                       
    │                                                                                                                                                                
    ▼                                                                                                                                                              
  Pricing Engine.Calculate(                                                                                                                                          
    capability="transcription",                                                                                                                                      
    provider="groq",                                                                                                                                                 
    actual_usage={duration_seconds: 142.3}                                                                                                                           
  ) → credits_actual = 15   (估算14，实际15)                                                                                                                       
    │                                                                                                                                                              
    ▼                                                                                                                                                              
  Wallet.Settle(reservation_id="rsv_abc123", actual=15)                                                                                                              
    │ 追加扣款 1 credit（有余额）                                                                                                                                    
    │ balance: 336 → 335                                                                                                                                             
    │                                                                                                                                                                
    ▼                                                                                                                                                              
  Usage Log.Record({                                                                                                                                                 
    user_id, capability="transcription",                                                                                                                             
    provider="groq", model="whisper-large-v3",                                                                                                                       
    input_units=142.3, unit_type="seconds",                                                                                                                          
    provider_cost_usd=0.000024,                                                                                                                                    
    credits_reserved=14, credits_charged=15,                                                                                                                         
    latency_ms=8300, status="success"                                                                                                                              
  })                                                                                                                                                                 
    │                                                                                                                                                                
    ▼                                                                                                                                                                
  Response → User {text: "...", credits_used: 15, balance: 335}                                                                                                      
                                                                                                                                                                   
  4.2 Fallback 数据流                                                                                                                                              
                                                                                                                                                                   
  AI Router → 选 Provider=Groq                                                                                                                                       
    │                                                                                                                                                                
    ▼                                                                                                                                                                
  Groq API 调用 → Timeout (30s)                                                                                                                                      
    │                                                                                                                                                                
    ▼                                                                                                                                                              
  AI Router.Fallback()                                                                                                                                               
    │ 记录 groq 失败，更新 Health Score（降权）                                                                                                                      
    │ 选 Provider=Azure（次选）
    │                                                                                                                                                                
    ▼                                                                                                                                                              
  Azure API 调用 → 成功                                                                                                                                              
    │ fallback_used=true, fallback_from="groq"                                                                                                                       
    │                                                                                                                                                                
    ▼ （后续流程相同，但 Usage Log 记录 fallback 信息）                                                                                                              
                                                                                                                                                                     
  ---                                                                                                                                                                
  5. Credits 生命周期                                                                                                                                                
                                                                                                                                                                     
  Credits 来源：                                                                                                                                                   
    ┌──────────────────────────────────────────────────────────────┐                                                                                                 
    │  Subscription Activation                                     │                                                                                               
    │  └→ Wallet.Add(amount=1000, type=subscription,              │                                                                                                
    │                expires_at=month_end)                         │                                                                                                 
    │                                                              │                                                                                               
    │  Gift Credits（运营活动）                                    │                                                                                                 
    │  └→ Wallet.Add(amount=200, type=gift,                       │                                                                                                  
    │                expires_at=30days_later)                      │                                                                                                 
    │                                                              │                                                                                                 
    │  Purchase（未来实现）                                        │                                                                                                 
    │  └→ Wallet.Add(amount=500, type=paid,                       │                                                                                                
    │                expires_at=never)                             │                                                                                                 
    └──────────────────────────────────────────────────────────────┘                                                                                               
                             │                                                                                                                                       
                             ▼ 进入 Wallet                                                                                                                           
    ┌──────────────────────────────────────────────────────────────┐                                                                                               
    │  Wallet Balance                                              │                                                                                                 
    │  ├── subscription_credits : 980   (月末清零)                │                                                                                                
    │  ├── gift_credits         : 200   (有过期时间)              │                                                                                                  
    │  └── paid_credits         : 500   (永不过期)                │                                                                                                  
    │  total: 1,680                                                │                                                                                               
    └──────────────────────────────────────────────────────────────┘                                                                                                 
                             │                                                                                                                                     
            ┌────────────────┼────────────────┐                                                                                                                      
            ▼                ▼                ▼                                                                                                                    
          消费顺序:  Subscription → Gift → Paid                                                                                                                      
                    （优先消耗"快过期"的）                                                                                                                         
                                                                                                                                                                     
    消费过程：                                                                                                                                                       
    ┌─────────────────────────────────────────┐                                                                                                                    
    │  Reserve(14)   → 锁定，不可被其他请求用 │                                                                                                                      
    │  Settle(15)    → 实际扣除 15            │                                                                                                                    
    │  Release()     → AI 失败时全额解锁      │                                                                                                                      
    └─────────────────────────────────────────┘                                                                                                                    
                                                                                                                                                                     
    月末结算：                                                                                                                                                       
    ┌─────────────────────────────────────────┐                                                                                                                      
    │  Cron Job: 每月1日 00:00 UTC            │                                                                                                                      
    │  1. Wallet.ExpireSubscriptionCredits()  │                                                                                                                      
    │  2. Subscription.Renew()               │                                                                                                                     
    │  3. Wallet.Add(new_subscription_quota) │                                                                                                                       
    └─────────────────────────────────────────┘                                                                                                                      
                                                                                                                                                                   
    过期处理：                                                                                                                                                       
    ┌─────────────────────────────────────────┐                                                                                                                      
    │  Gift Credits: expires_at < now → 清零  │                                                                                                                      
    │  Subscription Credits: month_end → 清零 │                                                                                                                      
    │  Paid Credits: 永不过期                 │                                                                                                                      
    └─────────────────────────────────────────┘                                                                                                                    
                                                                                                                                                                     
    退款：                                                                                                                                                           
    ┌─────────────────────────────────────────┐                                                                                                                      
    │  Refund(usage_log_id, amount)           │                                                                                                                      
    │  → 退入 GiftCredits（有效期 30 天）     │                                                                                                                      
    │  → 写入 WalletTransaction(type=refund)  │                                                                                                                    
    │  → 更新 UsageLog.status = "refunded"   │                                                                                                                       
    └─────────────────────────────────────────┘                                                                                                                      
                                                                                                                                                                     
  ---                                                                                                                                                                
  6. 一次 AI 调用从请求到扣费的完整流程                                                                                                                              
                                                                                                                                                                     
  以"用户上传视频做语音识别"为例，完整 12 步：                                                                                                                     
                                                                                                                                                                     
  Step 1  [Experience Layer]                                                                                                                                         
          POST /api/transcribe                                                                                                                                     
          Headers: Authorization: Bearer <jwt>                                                                                                                       
          Body: {file: audio.mp3, quality: "standard"}                                                                                                             
                                                                                                                                                                     
  Step 2  [Identity]                                                                                                                                               
          JWT 解码 → user_id = "usr_xyz"                                                                                                                             
          加载 UserSubscription → plan = "plus"                                                                                                                      
                                                                                                                                                                     
  Step 3  [Permission Engine]                                                                                                                                        
          Check(usr_xyz, CanTranscribe) → true                                                                                                                       
          Check(usr_xyz, CanUseStandardQuality) → true                                                                                                               
          （从缓存读取，命中率 > 99%）                                                                                                                               
                                                                                                                                                                     
  Step 4  [Input Analysis]                                                                                                                                           
          ffprobe 获取音频时长 → 142.3 秒                                                                                                                          
          构造 input_metadata = {duration_seconds: 142.3}                                                                                                            
                                                                                                                                                                     
  Step 5  [Pricing Engine - Estimate]                                                                                                                                
          Estimate(capability="transcription", quality="standard",                                                                                                   
                   plan="plus", input={duration_seconds: 142.3})                                                                                                   
                                                                                                                                                                     
          查 PricingPolicy: multiplier=2.5, base_unit=per_minute                                                                                                   
          查 ProviderCostTable: groq=$0.0001/min → 估算成本 = $0.0000237                                                                                             
          转 Credits: 0.0000237 × 2.5 × rate → 估算 14 Credits                                                                                                     
          加 10% buffer → reserve_amount = 15                                                                                                                        
                                                                                                                                                                   
  Step 6  [Wallet - Reserve]                                                                                                                                         
          Reserve(usr_xyz, 15)                                                                                                                                       
          检查余额：subscription=400, gift=50, paid=200 → total=650 ≥ 15 ✓                                                                                           
          优先从 subscription_credits 扣：400 → 385                                                                                                                  
          锁定 15 credits                                                                                                                                            
          → reservation_id = "rsv_20260716_001"                                                                                                                      
                                                                                                                                                                     
  Step 7  [AI Router - Select]                                                                                                                                       
          Route(capability="transcription", quality="standard",                                                                                                      
                plan="plus", input_metadata)                                                                                                                         
                                                                                                                                                                   
          Health Check:                                                                                                                                              
            groq: error_rate=0.1%, latency_p50=1.8s ✓                                                                                                              
            azure: error_rate=0.3%, latency_p50=4.2s ✓                                                                                                               
                                                                                                                                                                   
          Cost Optimization（plus plan 可用 groq, azure）:                                                                                                           
            groq estimated cost = $0.0000237                                                                                                                         
            azure estimated cost = $0.0000948                                                                                                                      
            groq wins                                                                                                                                                
                                                                                                                                                                   
          → ProviderHandle{provider="groq", model="whisper-large-v3",                                                                                                
                           timeout=60s}                                                                                                                              
         
  Step 8  [Provider Layer - Execute]                                                                                                                                 
          调用 Groq Whisper API                                                                                                                                    
          传入音频，等待响应...                                                                                                                                      
          8.3 秒后返回：                                                                                                                                           
          {                                                                                                                                                          
            "text": "...",                                                                                                                                           
            "segments": [...],                                                                                                                                     
            "duration": 142.3                                                                                                                                        
          }                                                                                                                                                        
                                                                                                                                                                     
  Step 9  [Pricing Engine - Calculate]                                                                                                                             
          Calculate(capability="transcription", provider="groq",                                                                                                     
                    actual_usage={duration_seconds: 142.3})
                                                                                                                                                                     
          实际成本 = 142.3/60 × $0.0001 = $0.0000237                                                                                                               
          乘以 Pricing Policy multiplier(2.5) = $0.0000593                                                                                                         
          换算 Credits = 13（实际比估算少）                                                                                                                          
                                                                                                                                                                     
  Step 10 [Wallet - Settle]                                                                                                                                          
          Settle(reservation_id="rsv_20260716_001", actual=13)                                                                                                       
          预扣 15，实际 13 → 退还 2                                                                                                                                  
          subscription_credits: 385 → 387（退还 2）                                                                                                                  
          最终扣 13 credits                                                                                                                                          
                                                                                                                                                                     
  Step 11 [Usage Log - Record]                                                                                                                                       
          {                                                                                                                                                          
            log_id: "log_20260716_001",                                                                                                                              
            user_id: "usr_xyz",                                                                                                                                      
            capability: "transcription",                                                                                                                           
            quality_tier: "standard",                                                                                                                              
            provider_id: "groq",                                                                                                                                     
            model_id: "whisper-large-v3",
            plan_tier: "plus",                                                                                                                                       
            input_units: 142.3,                                                                                                                                    
            input_unit_type: "seconds",                                                                                                                              
            provider_cost_usd: 0.0000237,                                                                                                                          
            credits_reserved: 15,                                                                                                                                    
            credits_charged: 13,                                                                                                                                   
            credits_refunded: 0,                                                                                                                                     
            latency_ms: 8300,                                                                                                                                      
            status: "success",                                                                                                                                       
            retry_count: 0,
            fallback_used: false,                                                                                                                                    
            requested_at: "2026-07-16T08:23:01Z",                                                                                                                  
            completed_at: "2026-07-16T08:23:09Z",                                                                                                                    
            reservation_id: "rsv_20260716_001"                                                                                                                     
          }                                                                                                                                                          
                                                                                                                                                                     
  Step 12 [Response]                                                                                                                                               
          {                                                                                                                                                          
            "text": "...",                                                                                                                                         
            "segments": [...],                                                                                                                                       
            "_meta": {                                                                                                                                             
              "credits_used": 13,
              "balance_remaining": 637,                                                                                                                            
              "request_id": "log_20260716_001"                                                                                                                     
            }                                                                                                                                                        
          }                                                                                                                                                        
                                                                                                                                                                     
  ---                                                                                                                                                                
  7. Provider 与 Billing 完全解耦
                                                                                                                                                                     
  问题：如果 Billing 直接感知 Provider，那么每次换 Provider 都要修改 Billing 代码。                                                                                
                                                                                                                                                                   
  解决方案：三层抽象隔离。                                                                                                                                           
                                                                                                                                                                   
  业务层视角：                                                                                                                                                       
    "用户使用了 transcription（standard），消耗了 13 Credits"                                                                                                      
    ← Billing 只知道这个                                                                                                                                             
                                                                                                                                                                     
  Provider 层视角：                                                                                                                                                
    "我调用了 Groq Whisper，处理了 142 秒音频，花了 $0.0000237"                                                                                                      
    ← Provider 只知道这个                                                                                                                                            
                                                                                                                                                                     
  连接两者的：Pricing Engine 中的 Provider Cost Table                                                                                                                
    ← 这是唯一感知 Provider 存在的地方                                                                                                                               
                                                                                                                                                                     
  隔离保证：                                                                                                                                                         
                                                                                                                                                                     
    ┌──────────────────────────────────────────────────────┐                                                                                                         
    │  Wallet      ← 只操作 Credits，不知道 Provider       │                                                                                                       
    │  Subscription ← 只定义套餐权益，不绑定 Provider      │                                                                                                         
    │  Permission   ← 只管 Capability，不知道 Provider      │                                                                                                      
    │  Usage Log    ← 记录 Provider，但不做 Billing 决策   │                                                                                                       
    │                                                      │                                                                                                         
    │  Provider Cost Table ← 唯一 Billing×Provider 交叉点  │                                                                                                         
    └──────────────────────────────────────────────────────┘                                                                                                         
                                                                                                                                                                     
  实际效果验证：                                                                                                                                                     
                                                                                                                                                                     
    场景A：Groq 涨价                                                                                                                                                 
      → 只改 Provider Cost Table 的 groq 单价                                                                                                                        
      → Pricing Engine 自动重新计算                                                                                                                                  
      → Wallet / Subscription / Permission 零修改                                                                                                                    
                                                                                                                                                                   
    场景B：某 Capability 更换默认 Provider                                                                                                                           
      → 只改 AI Router 的路由策略                                                                                                                                  
      → Billing 完全无感知                                                                                                                                           
      → 用户侧只是"响应快了"或"成本降了"                                                                                                                             
                                                                                                                                                                     
    场景C：新增 Provider（DeepSeek v3）                                                                                                                              
      → 在 Provider Layer 增加 deepseek_v3.py                                                                                                                        
      → 在 Provider Cost Table 增加一行                                                                                                                              
      → 在 AI Router 路由策略中加入                                                                                                                                  
      → Billing / Wallet / Subscription 零修改                                                                                                                       
                                                                                                                                                                     
    场景D：废弃 Provider                                                                                                                                           
      → AI Router 中将其 Health Score 设为 0（永不选择）                                                                                                             
      → Provider Cost Table 标记 deprecated                                                                                                                          
      → 存量 Usage Log 记录保留（历史准确性）                                                                                                                        
      → 零其他改动                                                                                                                                                   
                                                                                                                                                                     
  ---                                                                                                                                                              
  8. 支持未来新增 Provider                                                                                                                                           
                                                                                                                                                                   
  操作步骤（3 步，全部隔离在各自模块内）：                                                                                                                           
                                                                                                                                                                   
  Step 1: 实现 Provider Adapter（Provider Layer）                                                                                                                    
    在 backend/ai/provider/ 新建 new_provider.py                                                                                                                   
    实现 ProviderAdapter 协议：                                                                                                                                      
      - transcribe(audio, model, options) → TranscriptionResult                                                                                                    
      - translate(text, src_lang, tgt_lang) → TranslationResult                                                                                                      
      - tts(text, voice, options) → AudioResult                                                                                                                      
      - get_usage(response) → UsageMetrics  ← 返回实际用量                                                                                                           
                                                                                                                                                                     
    新 Provider 只需实现它支持的 Capability，其他返回 NotSupported                                                                                                   
                                                                                                                                                                     
  Step 2: 注册 Provider 元数据                                                                                                                                       
    在 Provider Cost Table 插入记录：                                                                                                                                
      {provider_id: "anthropic", model_id: "claude-haiku",                                                                                                           
       capability: "translation", unit: "per_1k_tokens",                                                                                                             
       unit_price: 0.00025}                                                                                                                                        
                                                                                                                                                                   
  Step 3: 注册路由规则                                                                                                                                               
    在 AI Router 配置中添加：                                                                                                                                        
      capability="translation", quality="premium" → providers=[anthropic, gemini]                                                                                    
      fallback_chain=[anthropic → gemini → deepseek]                                                                                                                 
                                                                                                                                                                     
  完成。Billing、Wallet、Subscription、Permission 零改动。                                                                                                         
                                                                                                                                                                     
  Provider 契约（ProviderAdapter Protocol）：                                                                                                                        
                                                                                                                                                                     
    class ProviderAdapter(Protocol):                                                                                                                                 
      provider_id: str                                                                                                                                               
      supported_capabilities: list[CapabilityType]                                                                                                                 
                                                                                                                                                                     
      def execute(                                                                                                                                                 
        self,                                                                                                                                                      
        capability: CapabilityType,                                                                                                                                  
        input: CapabilityInput,
        options: ProviderOptions                                                                                                                                     
      ) -> CapabilityOutput: ...                                                                                                                                   
                                                                                                                                                                   
      def get_actual_usage(                                                                                                                                          
        self,                                                                                                                                                      
        response: ProviderResponse                                                                                                                                   
      ) -> ActualUsage: ...  # ← 关键：Provider 必须汇报真实用量                                                                                                   
                                                                                                                                                                     
      def health_check(self) -> HealthStatus: ...                                                                                                                  
                                                                                                                                                                   
  ---                                                                                                                                                                
  9. 支持未来新增 Capability
                                                                                                                                                                     
  新增一个 Capability 需要触及的层（最小变更集）：                                                                                                                 
                                                                                                                                                                   
  必须修改：                                                                                                                                                         
    ① Capability 枚举    → 增加 CapabilityType.video_summary                                                                                                       
    ② Permission 枚举    → 增加 CanVideoSummary                                                                                                                      
    ③ Provider Adapter  → 在支持该能力的 Provider 实现 video_summary()                                                                                             
    ④ Pricing Policy    → 配置 video_summary 的收费策略                                                                                                              
    ⑤ Experience Layer  → 新增 /api/video-summary 路由                                                                                                               
                                                                                                                                                                   
  不需要修改：                                                                                                                                                       
    - Wallet（只管 Credits 进出）                                                                                                                                  
    - AI Router（能力由路由配置驱动，代码不变）                                                                                                                      
    - Subscription 代码（只需在运营后台给套餐加上新权限）                                                                                                          
    - Usage Log（通用记录，Capability 是数据字段）                                                                                                                   
    - Identity                                                                                                                                                       
                                                                                                                                                                     
  新 Capability 上线流程：                                                                                                                                           
                                                                                                                                                                     
    1. 开发阶段：实现 Provider Adapter 中的 capability 方法                                                                                                          
    2. 测试阶段：Dry Run Mode 验证路由选择                                                                                                                           
    3. 定价阶段：运营配置 PricingPolicy（无需部署）                                                                                                                  
    4. 上线阶段：Permission Engine 开放给对应套餐                                                                                                                    
    5. 灰度阶段：先给 Pro 开放，观察 Usage Log 成本数据                                                                                                            
    6. 全量阶段：开放给 Plus / Free                                                                                                                                  
                                                                                                                                                                     
  实际例子——未来新增"AI 配音"（Dubbing）：                                                                                                                           
                                                                                                                                                                     
    新增：                                                                                                                                                           
      CapabilityType.dubbing                                                                                                                                         
      CanDubbing                                                                                                                                                   
      DubbingInput {text, target_language, voice_style}                                                                                                              
      DubbingOutput {audio_url, duration}                                                                                                                          
      Provider: gemini_tts（已有）+ azure_neural（已有）                                                                                                           
      PricingPolicy: per_minute_output × 2.0                                                                                                                       
                                                                                                                                                                     
    不变：Wallet, Subscription架构, Router代码, UsageLog结构                                                                                                         
                                                                                                                                                                     
  ---                                                                                                                                                                
  10. 支持未来新增收费策略                                                                                                                                           
                                                                                                                                                                     
  当前支持的 Formula 类型：                                                                                                                                          
                                                                                                                                                                   
    FormulaType.fixed                                                                                                                                                
      例：每次导出 SRT = 5 Credits（不管文件多大）                                                                                                                 
      适用：低成本、固定操作                                                                                                                                         
                                                                                                                                                                   
    FormulaType.cost_multiplier                                                                                                                                      
      例：Credits = 真实API成本(USD) × 汇率 × 2.5                                                                                                                    
      适用：成本波动的 AI 调用（转录、翻译）                                                                                                                         
                                                                                                                                                                     
    FormulaType.tiered                                                                                                                                               
      例：前 100 字符免费，101-1000 字符 1 Credit/100字，                                                                                                            
           1001+ 字符 0.8 Credit/100字（阶梯优惠）                                                                                                                   
      适用：激励用户增加用量                                                                                                                                         
                                                                                                                                                                     
  未来可扩展的 Formula 类型：                                                                                                                                        
                                                                                                                                                                     
    FormulaType.subscription_free                                                                                                                                    
      套餐内功能，Credits 扣 0（Wallet 记录但不实际扣）                                                                                                              
      例：Free 套餐每天前 3 次转录免费                                                                                                                             
                                                                                                                                                                     
    FormulaType.dynamic_price                                                                                                                                      
      根据系统负载实时调整价格（低峰期打折）                                                                                                                         
                                                                                                                                                                     
    FormulaType.bundle                                                                                                                                               
      批量操作打包定价（10 个视频一起上传享 8 折）                                                                                                                   
                                                                                                                                                                     
    FormulaType.event_price                                                                                                                                        
      限时活动价格（双十一半价）                                                                                                                                     
                                                                                                                                                                     
  扩展方式：                                                                                                                                                         
    - 在 FormulaType 枚举增加新类型                                                                                                                                  
    - 在 PricingEngine.Calculate() 增加对应分支                                                                                                                      
    - 在 PricingPolicy 表填入新 formula 类型的参数                                                                                                                   
    - 无需修改 Wallet / Router / Provider                                                                                                                          
                                                                                                                                                                     
  定价参数变更（无需部署）：                                                                                                                                         
    所有 PricingPolicy 存储在数据库，运营后台可实时修改。                                                                                                            
    变更立即生效，无需代码发布。                                                                                                                                     
    支持历史版本：effective_from / effective_to 字段保证历史账单准确。                                                                                               
                                                                                                                                                                     
  ---                                                                                                                                                                
  11. 支持未来新增会员套餐                                                                                                                                           
                                                                                                                                                                     
  当前设计已支持套餐热更新：                                                                                                                                         
                                                                                                                                                                     
    PlanDefinition 存储在数据库，不硬编码在代码中。                                                                                                                  
    运营后台可随时：                                                                                                                                               
      - 调整月度 Credits 配额                                                                                                                                        
      - 新增 / 移除套餐包含的 Capabilities                                                                                                                           
      - 调整允许的 Quality Tier                                                                                                                                    
      - 修改允许的 Provider Pool                                                                                                                                     
                                                                                                                                                                     
  新增套餐（例：「学生套餐」）：                                                                                                                                     
                                                                                                                                                                     
    Step 1: 在 PlanDefinition 插入新行                                                                                                                             
      {plan_id: "student", monthly_credits: 500,                                                                                                                   
       capabilities: [transcription, translation],                                                                                                                 
       quality_tiers: [economy, standard],                                                                                                                           
       price: $2.99/month}                                                                                                                                         
                                                                                                                                                                     
    Step 2: 在 Permission 配置中关联权限集                                                                                                                         
      student → [CanTranscribe, CanTranslate, CanExport]                                                                                                             
                                                                                                                                                                     
    Step 3: 在 AI Router 配置中关联 Provider Pool                                                                                                                    
      student → [groq, deepseek]（低成本 Provider）                                                                                                                  
                                                                                                                                                                     
    Step 4: 前端展示（添加套餐卡片）                                                                                                                                 
                                                                                                                                                                   
    代码层面零修改。                                                                                                                                                 
                                                                                                                                                                     
  套餐迁移（用户从 Plus 升级到 Pro）：                                                                                                                               
                                                                                                                                                                     
    1. 创建新 UserSubscription（pro, started_at=now）                                                                                                              
    2. 旧订阅标记 cancelled（Credits 保留到月末）                                                                                                                    
    3. Permission Engine 立即更新（缓存 invalidate）                                                                                                               
    4. Wallet 发放 Pro 套餐 Credits 差额（按比例）                                                                                                                   
    5. Usage Log 记录套餐变更事件                                                                                                                                  
                                                                                                                                                                     
  套餐降级（Pro → Plus）：                                                                                                                                         
                                                                                                                                                                     
    1. 在月末生效（不立即降级）                                                                                                                                    
    2. 当月继续享受 Pro 权限                                                                                                                                         
    3. 月末 Cron Job 执行降级 + 重置 Credits                                                                                                                       
                                                                                                                                                                     
  套餐废弃（下架旧套餐）：                                                                                                                                         
                                                                                                                                                                     
    1. PlanDefinition.status = deprecated（新用户不可购买）                                                                                                          
    2. 存量用户继续享有，直到取消                                                                                                                                    
    3. 数据库永久保留（历史账单需要）                                                                                                                                
                                                                                                                                                                     
  ---                                                                                                                                                              
  12. 风险分析                                                                                                                                                       
                                                                                                                                                                     
  12.1 技术风险                                                                                                                                                      
                                                                                                                                                                     
  ┌───────────────────────────────────────────────────────────────┬──────┬──────┬───────────────────────────────────────────────┐                                  
  │                             风险                              │ 概率 │ 影响 │                   缓解策略                    │                                  
  ├───────────────────────────────────────────────────────────────┼──────┼──────┼───────────────────────────────────────────────┤                                  
  │ Wallet 并发双重扣款                                           │ 中   │ 高   │ 乐观锁（version 字段）+ Reserve/Settle 两阶段 │                                    
  ├───────────────────────────────────────────────────────────────┼──────┼──────┼───────────────────────────────────────────────┤
  │ AI Router 选错 Provider 导致成本超预算                        │ 中   │ 中   │ Cost Circuit Breaker + 每日成本告警           │                                    
  ├───────────────────────────────────────────────────────────────┼──────┼──────┼───────────────────────────────────────────────┤                                  
  │ Pricing Policy 配置错误导致少收费                             │ 低   │ 高   │ 审批流 + 历史版本 + 测试环境验证              │                                  
  ├───────────────────────────────────────────────────────────────┼──────┼──────┼───────────────────────────────────────────────┤                                    
  │ Provider Health Check 误判导致全部 Fallback 到高成本 Provider │ 低   │ 高   │ Health Score 衰减算法 + 人工告警阈值          │                                    
  ├───────────────────────────────────────────────────────────────┼──────┼──────┼───────────────────────────────────────────────┤                                    
  │ Usage Log 写入失败（AI 成功但不记录）                         │ 低   │ 高   │ 异步写入 + 重试队列 + 对账机制                │                                    
  ├───────────────────────────────────────────────────────────────┼──────┼──────┼───────────────────────────────────────────────┤                                  
  │ Credits 月末结算 Cron 失败                                    │ 低   │ 高   │ 幂等设计 + 失败告警 + 人工补跑                │                                    
  ├───────────────────────────────────────────────────────────────┼──────┼──────┼───────────────────────────────────────────────┤                                  
  │ JWT 失效但 Permission 缓存仍有效                              │ 中   │ 中   │ 用户状态变更时主动 invalidate 缓存            │                                    
  └───────────────────────────────────────────────────────────────┴──────┴──────┴───────────────────────────────────────────────┘                                  
                                                                                                                                                                     
  12.2 产品风险                                                                                                                                                    
                                                                                                                                                                     
  ┌───────────────────────────────────────────┬──────────────────────────────────────────────┐                                                                     
  │                   风险                    │                   缓解策略                   │                                                                       
  ├───────────────────────────────────────────┼──────────────────────────────────────────────┤                                                                     
  │ Credits 不透明，用户不信任                │ Usage Log 对用户开放查询，每次调用后返回余额 │
  ├───────────────────────────────────────────┼──────────────────────────────────────────────┤
  │ Credits 耗尽体验差                        │ 提前在余额 < 20% 时推送提醒                  │
  ├───────────────────────────────────────────┼──────────────────────────────────────────────┤                                                                     
  │ 免费用户用量超出预期，成本失控            │ Free 套餐加 Rate Limiter（每日最大调用次数） │                                                                     
  ├───────────────────────────────────────────┼──────────────────────────────────────────────┤                                                                       
  │ Provider 大规模故障，Credits 被扣但无结果 │ Wallet.Release() 在超时/失败时自动退款       │                                                                       
  ├───────────────────────────────────────────┼──────────────────────────────────────────────┤                                                                       
  │ 定价策略被用户"算出来"套利                │ 定价公式不对外暴露，只展示 Credits 数字      │                                                                       
  └───────────────────────────────────────────┴──────────────────────────────────────────────┘                                                                     
                                                                                                                                                                     
  12.3 架构风险                                                                                                                                                    
                                                                                                                                                                     
  ┌───────────────────────────────────────┬────────────────────────────────────────────────────────────────┐                                                       
  │                 风险                  │                            缓解策略                            │                                                         
  ├───────────────────────────────────────┼────────────────────────────────────────────────────────────────┤                                                       
  │ 模块边界腐化，业务代码直接查 Provider │ Code Review 强制：任何 provider_id 出现在 Billing 模块即为违规 │
  ├───────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
  │ Pricing Policy 无限增长，难以维护     │ 定期 audit，废弃超过 1 年未使用的 Policy                       │
  ├───────────────────────────────────────┼────────────────────────────────────────────────────────────────┤                                                       
  │ Usage Log 数据量爆炸                  │ 热数据保留 90 天，冷数据归档到对象存储                         │                                                       
  ├───────────────────────────────────────┼────────────────────────────────────────────────────────────────┤                                                         
  │ 缺少测试导致重构破坏计费逻辑          │ Pricing Engine 必须有单元测试覆盖所有 Formula                  │                                                         
  └───────────────────────────────────────┴────────────────────────────────────────────────────────────────┘                                                         
                                                                                                                                                                     
  ---                                                                                                                                                              
  13. 推荐实施顺序                                                                                                                                                   
                                                                                                                                                                   
  ▎ 原则：每个 Task 独立可测试，完成后平台能正常运行，下一个 Task 在上一个的基础上叠加。                                                                             
                                                                                                                                                                   
  Phase 0：数据基础（约 1 周）                                                                                                                                       
                                                                                                                                                                   
  Task 0.1: 设计并创建数据库 Schema                                                                                                                                  
    Tables: users, user_subscriptions, plan_definitions,                                                                                                             
            wallets, wallet_transactions,                                                                                                                            
            provider_cost_table, pricing_policies,                                                                                                                   
            usage_logs                                                                                                                                               
    工具: SQLite（开发）→ PostgreSQL（生产，Railway 提供）                                                                                                           
    产出: migration SQL 文件                                                                                                                                         
                                                                                                                                                                     
  Task 0.2: 实现 Identity 模块（数据层）                                                                                                                           
    User + Profile + UserSubscription 的 CRUD                                                                                                                        
    不实现登录，用 ADMIN_KEY 临时创建测试用户                                                                                                                        
    产出: identity.py                                                                                                                                                
                                                                                                                                                                     
  Task 0.3: 实现 Subscription 数据结构                                                                                                                               
    PlanDefinition 初始化脚本（插入 Free/Plus/Pro/Enterprise）                                                                                                       
    UserSubscription CRUD                                                                                                                                            
    产出: subscription.py + seed_plans.sql                                                                                                                           
                                                                                                                                                                     
  Phase 1：核心计费链（约 2 周）                                                                                                                                     
                                                                                                                                                                   
  Task 1.1: 实现 Wallet 模块                                                                                                                                         
    Reserve / Settle / Release / Add / Refund                                                                                                                        
    乐观锁并发控制
    WalletTransaction 写入                                                                                                                                           
    单元测试：并发扣款不超发                                                                                                                                       
    产出: wallet.py + test_wallet.py                                                                                                                                 
                                                                                                                                                                   
  Task 1.2: 实现 Pricing Engine（基础版）                                                                                                                            
    Provider Cost Table CRUD                                                                                                                                       
    PricingPolicy CRUD                                                                                                                                               
    Estimate() / Calculate()：先实现 cost_multiplier 公式                                                                                                          
    单元测试：各 Capability 的定价计算                                                                                                                               
    产出: pricing.py + test_pricing.py                                                                                                                               
                                                                                                                                                                   
  Task 1.3: 实现 Usage Log 模块                                                                                                                                      
    UsageLog 写入（同步 + 异步两种模式）                                                                                                                           
    基本查询接口（by user_id, by date）                                                                                                                              
    产出: usage_log.py                                                                                                                                               
                                                                                                                                                                   
  Phase 2：路由与权限（约 1 周）                                                                                                                                     
                                                                                                                                                                     
  Task 2.1: 实现 Permission Engine                                                                                                                                   
    PermissionSet 枚举                                                                                                                                               
    Check() / CheckAll() + 缓存                                                                                                                                    
    Plan → PermissionSet 映射                                                                                                                                        
    产出: permission.py + test_permission.py                                                                                                                       
                                                                                                                                                                     
  Task 2.2: 实现 AI Router（基础版）                                                                                                                                 
    静态路由：capability → provider 优先级列表                                                                                                                       
    Fallback Chain（只做 2 层 Fallback）                                                                                                                             
    暂不实现 Health Check（下一步）                                                                                                                                  
    产出: router.py                                                                                                                                                
                                                                                                                                                                     
  Task 2.3: 实现 AI Router Health Check                                                                                                                              
    后台线程定时 ping Provider                                                                                                                                       
    Health Score 更新                                                                                                                                                
    路由时考虑 Health Score                                                                                                                                          
    产出: router.py (更新) + health.py                                                                                                                             
                                                                                                                                                                     
  Phase 3：集成与连通（约 1 周）                                                                                                                                     
                                                                                                                                                                     
  Task 3.1: 将现有 /api/transcribe 接入完整调用链                                                                                                                    
    现有路由：直接调 Provider                                                                                                                                        
    新路由：Permission → Pricing.Estimate → Wallet.Reserve                                                                                                           
            → Router → Provider → Pricing.Calculate                                                                                                                  
            → Wallet.Settle → UsageLog.Record                                                                                                                        
    保持 HTTP API 路径和响应格式不变（CLAUDE.md 规定）                                                                                                               
    产出: 修改 app.py，新增 commerce/ 子包                                                                                                                           
                                                                                                                                                                     
  Task 3.2: 将 /api/translate 接入调用链                                                                                                                             
    同上，接入翻译链路                                                                                                                                               
                                                                                                                                                                     
  Task 3.3: 将 /api/tts 接入调用链                                                                                                                                   
    同上，接入 TTS 链路                                                                                                                                              
                                                                                                                                                                     
  Task 3.4: 将 /api/pronunciation 接入调用链                                                                                                                         
    同上，接入发音评分链路
                                                                                                                                                                     
  Phase 4：运营工具（约 1 周）                                                                                                                                     
                                                                                                                                                                   
  Task 4.1: 管理员 API（基于现有 ADMIN_KEY 机制）                                                                                                                    
    GET  /api/admin/users          → 用户列表                                                                                                                      
    GET  /api/admin/usage          → 用量报表                                                                                                                        
    POST /api/admin/credits/grant  → 赠送 Credits                                                                                                                    
    POST /api/admin/credits/refund → 手动退款                                                                                                                        
    GET  /api/admin/costs          → Provider 成本报表                                                                                                               
                                                                                                                                                                     
  Task 4.2: 用户侧余额 API                                                                                                                                           
    GET  /api/user/wallet          → 余额 + 明细                                                                                                                     
    GET  /api/user/usage           → 本月用量历史                                                                                                                    
    （前端显示 Credits 余额，本阶段简单文字即可）                                                                                                                  
                                                                                                                                                                     
  Task 4.3: Credits 月末结算 Cron                                                                                                                                    
    每月 1 日自动重置 Subscription Credits                                                                                                                           
    失败告警                                                                                                                                                         
                                                                                                                                                                     
  Phase 5：生产加固（约 1 周）                                                                                                                                       
                                                                                                                                                                     
  Task 5.1: 对账机制                                                                                                                                               
    每日：Usage Log 总扣费 ≈ Wallet 总减少额（允许 0.1% 误差）                                                                                                       
    告警：超出阈值时发邮件/Slack                                                                                                                                   
                                                                                                                                                                     
  Task 5.2: Rate Limiter（Free 套餐保护）                                                                                                                          
    Free 用户：每日最多 N 次调用                                                                                                                                     
    基于 Redis / 内存计数                                                                                                                                            
                                                                                                                                                                     
  Task 5.3: 监控 Dashboard                                                                                                                                           
    Grafana / 简单 HTML 图表                                                                                                                                         
    关键指标：日活用量、成本、Fallback 率、Credits 消耗速度                                                                                                          
                                                                                                                                                                     
  实施里程碑总结                                                                                                                                                     
                                                                                                                                                                     
  Week 1-2   Phase 0 + Phase 1   数据结构 + 计费核心 可独立测试                                                                                                      
  Week 3     Phase 2              路由 + 权限 可独立测试                                                                                                             
  Week 4     Phase 3              全链路连通，生产可用（Credits 开始生效）                                                                                           
  Week 5     Phase 4              运营工具上线                                                                                                                       
  Week 6     Phase 5              生产加固                                                                                                                           
  Week 7+    Phase 6（未列）      支付集成（Stripe / 微信 / Apple Pay）                                                                                              
                                                                                                                                                                     
  ---                                                                                                                                                                
  附录：核心数据类型速查                                                                                                                                             
                                                                                                                                                                     
  # 能力类型（Capability）                                                                                                                                         
  CapabilityType = Literal[                                                                                                                                          
      "transcription",        # 语音识别                                                                                                                             
      "translation",          # 翻译
      "tts",                  # 文本转语音                                                                                                                           
      "pronunciation",        # 发音评分                                                                                                                           
      "romanize",             # 拼音/罗马拼音                                                                                                                        
      "word_definition",      # 单词释义                                                                                                                           
      "export",               # 导出 SRT / 视频                                                                                                                      
      "shadowing",            # 影子跟读（未来）                                                                                                                   
      "dubbing",              # AI 配音（未来）                                                                                                                      
  ]                                                                                                                                                                
                                                                                                                                                                     
  # 质量层级（Quality Tier）                                                                                                                                         
  QualityTier = Literal["economy", "standard", "premium"]                                                                                                            
                                                                                                                                                                     
  # 套餐层级（Plan Tier）                                                                                                                                            
  PlanTier = Literal["free", "plus", "pro", "enterprise"]                                                                                                          
                                                                                                                                                                     
  # Credits 类型（Credit Type）                                                                                                                                      
  CreditType = Literal["subscription", "gift", "paid"]
                                                                                                                                                                     
  # 计费单位（Cost Unit）                                                                                                                                          
  CostUnit = Literal[                                                                                                                                              
      "per_minute",           # 音频/视频（转录、TTS、评分）                                                                                                         
      "per_1k_chars",         # 翻译、拼音                                                                                                                         
      "per_1k_tokens",        # LLM（未来）                                                                                                                          
      "per_request",          # 固定费用                                                                                                                             
      "per_image",            # 图像处理（未来）                                                                                                                     
  ]                                                                                                                                                                  
                                                                                                                                                                     
  ---                                                                                                                                                                
  文档状态：架构设计完成，等待 Review 后进入 Phase 0 实施。 