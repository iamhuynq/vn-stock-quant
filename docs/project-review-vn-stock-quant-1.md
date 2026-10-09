# Review tổng thể Project `vn-stock-quant`

> Báo cáo review kiến trúc, research workflow, kết quả thực nghiệm, validation, backtest và roadmap phát triển cho nền tảng quantitative research chứng khoán Việt Nam.

---

## 1. Tóm tắt điều hành

`vn-stock-quant` hiện đã vượt xa phạm vi của một dashboard phân tích cổ phiếu đơn thuần. Project đang tiến gần tới một **nền tảng quantitative research** thực thụ.

Kiến trúc khái niệm hiện tại:

```text
FireAnt Crawler
      ↓
Raw / Normalized Data
      ↓
DuckDB Warehouse
      ↓
Feature Engine
      ↓
Pattern Discovery
      ↓
Event Study
      ↓
Cross-stock / Industry Analysis
      ↓
Backtest
      ↓
Daily Pipeline
      ↓
Paper Trading / UI
```

Điểm mạnh nhất của project không nằm ở một trading signal cụ thể, mà nằm ở **research discipline**:

```text
Hypothesis
   ↓
Preregistration
   ↓
Research
   ↓
Validation
   ↓
Holdout
   ↓
Backtest
   ↓
Decision
```

Điều đáng giá nhất là hệ thống đã bắt đầu có khả năng **loại bỏ những hypothesis nhìn rất đẹp trong quá khứ nhưng không sống sót ngoài mẫu**.

### Đánh giá tổng thể

| Hạng mục | Đánh giá |
|---|---:|
| Kiến trúc research | 8/10 |
| Data / research pipeline | 8/10 |
| Kỷ luật thống kê | 8/10 |
| Tư duy reproducibility | 8/10 |
| Trading implementation | 6.5/10 |
| Portfolio / risk layer | 6/10 |
| Factor / regime architecture | 5/10 |
| Tiềm năng dài hạn | 9/10 |

Hướng phát triển tiếp theo nên chuyển từ:

```text
Feature → Pattern → Backtest
```

sang:

```text
Feature
   ↓
Predictive Information
   ↓
Economic Value
   ↓
Strategy
   ↓
Portfolio
   ↓
Out-of-Sample Decision
```

---

# 2. Kiến trúc hiện tại

Các module research chính:

```text
src/quant_research/
├── backtest/
├── cross/
├── build.py
├── cli.py
├── daily.py
├── daily_report.py
├── engine.py
├── event_study.py
├── events.py
├── patterns.py
├── report.py
├── results.py
├── sanity.py
├── stats.py
└── sql/
```

Data collection được tách riêng:

```text
src/fireant_crawler/
```

Project cũng có một hệ thống documentation research khá đầy đủ:

```text
feature-engine-plan.md
pattern-discovery-plan.md
event-engine-plan.md
cross-stock-plan.md
group-analysis-plan.md
backtest-plan.md
fundamental-plan.md
dashboard-plan.md
data-dictionary.md
...
```

Việc tách:

```text
Crawler
  ↓
Warehouse
  ↓
Research
  ↓
Backtest
  ↓
UI
```

là hợp lý và có nền tảng tốt để mở rộng.

---

# 3. Điểm mạnh lớn nhất — Research Workflow

Project hiện có một research lifecycle khá tốt:

```text
DRAFT
 ↓
PREREGISTERED
 ↓
RESEARCH
 ↓
CANDIDATE
 ↓
VALIDATION
 ↓
HOLDOUT
 ↓
VALIDATED
 ├── ACTIVE
 ├── FAILED
 └── EXPIRED
```

Nên biến lifecycle này thành một **state machine thực sự trong software** thay vì chỉ tồn tại trong documentation.

Mỗi research result quan trọng nên có metadata bất biến:

```text
dataset_version
feature_version
hypothesis_version
strategy_version
code_commit
run_id
preregistration_hash
```

Nhờ vậy hệ thống có thể trả lời:

> "Tại sao kết quả hôm nay khác kết quả 6 tháng trước?"

thay vì chỉ lưu kết quả mới nhất.

---

# 4. Phân biệt 3 khái niệm cực kỳ quan trọng

Một trong những kết luận quan trọng nhất từ toàn bộ review:

```text
Predictive Information
        ≠
Economic Value
        ≠
Strategy Alpha
```

## Predictive Information

Feature có chứa thông tin thống kê về future return hay không?

Ví dụ:

```text
Order imbalance
        ↓
future return
```

có thể có quan hệ thống kê.

## Economic Value

Quan hệ đó có còn giá trị sau:

- transaction cost
- spread
- slippage
- turnover
- liquidity
- benchmark
- execution timing

hay không?

## Strategy Alpha

Cuối cùng, portfolio implementation có thực sự tạo ra alpha ngoài các benchmark/control hay không?

Đây là cấp độ mạnh nhất.

Order imbalance là ví dụ rất tốt:

```text
Predictive information = YES
Economic value        = NO
Standalone strategy   = NO
```

Đây là insight rất quan trọng cho kiến trúc tương lai.

---

# 5. Review Cross-Stock Research

## 5.1 Correlation

Research đến 2023-12-31 cho thấy excess-return correlation trung bình chỉ khoảng:

```text
0.03 – 0.19
```

theo từng năm với cửa sổ 120 phiên.

Tuy nhiên một số nhóm có correlation cao và khá bền:

- SSI – HCM
- SD6 / SD7 / SD9
- BSR – OIL
- PVC – PVE

Ví dụ:

```text
SSI / HCM ≈ 0.63
```

mean correlation trên 166 monthly snapshots.

Nhưng các quan hệ này không đủ phổ quát và ổn định để tự động trở thành trading alpha.

---

# 6. Correlation Cluster

Correlation clusters chỉ tương quan yếu với ICB level-2 industry.

Adjusted Rand Index:

```text
0.02 – 0.25
```

Điều này cho thấy:

```text
Industry Classification
        ≠
Empirical Co-movement
```

Đây là một phát hiện tốt cho **risk/exposure analysis**, hơn là dùng trực tiếp cho stock prediction.

---

# 7. Stability của Correlation Matrix

| Cửa sổ | Stability |
|---|---:|
| 60 phiên | 0.28 |
| 120 phiên | 0.39 |
| 250 phiên | 0.53 |

Correlation dài hạn ổn định hơn, nhưng từng pair vẫn có thể drift.

Do đó không nên xây quá nhiều chiến lược dựa trên pair-level correlation ngắn hạn.

---

# 8. Lead-Lag Research

Close-to-close lead-lag đôi khi cho kết quả có ý nghĩa thống kê.

Nhưng khi chuyển sang timing có thể trade được:

```text
Next Open → Close
```

thì hiệu ứng biến mất.

| Lag | Effect |
|---|---:|
| 1 | -0.0001 |
| 2 | -0.0010 |
| 3 | -0.0004 |
| 5 | -0.0010 |

Không có lag nào significant.

Khả năng cao phần lớn hiệu ứng đến từ:

- opening gap
- stale closing prices
- nonsynchronous trading

chứ không phải alpha có thể giao dịch.

### Quy tắc nên trở thành chuẩn của platform

> Một quan hệ timing chỉ có ý nghĩa khi được kiểm tra tại thời điểm execution thực tế có thể xảy ra.

---

# 9. Các Cross-Stock Hypothesis

## H1 — Industry leaders → followers

Kết quả:

```text
5d  = +0.12%, t=2.3, q=0.049
10d = +0.11%
20d = +0.09%
```

Nhưng hiệu ứng thấp hơn khoảng:

```text
0.4% round-trip cost
```

### Kết luận

```text
Không có economic value đủ để trade.
```

---

## H2 — Large caps → small caps

Sau market control:

```text
5d  slope = 0.19, q=0.058
10d slope = 0.21, q=0.24
20d slope = 0.22, q=0.57
```

### Kết luận

```text
Không có evidence đủ mạnh.
```

---

## H3 — Leader tăng +5%, follower đi ngang

```text
n = 192 dates

5d  = +0.16%
10d = -0.11%
20d = -0.33%
```

Không significant.

### Kết luận

```text
Không có spillover có thể trade.
```

---

# 10. Cointegration Research

Hypothesis:

> Khi spread > 2 sigma, mua leg đang rẻ hơn để chờ mean reversion.

Kết quả:

```text
5d  =  0.00%
10d = -0.11%
20d = -0.13%
```

Mean absolute z-score:

```text
2.28 → 2.44 → 2.65
```

Spread tiếp tục mở rộng thay vì mean-revert.

### Kết luận

```text
Statistical cointegration
        ≠
Short-term tradable mean reversion
```

---

# 11. Quyết định cuối cùng cho Cross-Stock

Cross-stock family không tìm được candidate đáng để đưa vào preregistered validation.

Quyết định đúng là:

> Không sử dụng cross-stock prediction như nguồn standalone trading alpha ở thời điểm hiện tại.

Nhưng module vẫn rất hữu ích cho:

- peer discovery
- correlation clusters
- co-movement
- risk concentration
- diversification
- industry structure

---

# 12. Group / Industry Analysis

Industry indexes có mức correlation cao hơn rất nhiều so với individual stocks.

Sau khi loại VNINDEX exposure:

```text
Industry: 0.20 – 0.58
Stocks:   0.03 – 0.19
```

Stability:

| Window | Industry | Stocks |
|---|---:|---:|
| 60 | 0.61 | 0.27 |
| 120 | 0.73 | 0.38 |
| 250 | 0.82 | 0.53 |

Điều này cho thấy **industry-level structure ổn định hơn stock-level structure rất nhiều**.

Đây là cơ sở tốt để phát triển:

```text
Factor Engine
Regime Engine
Exposure Engine
```

---

# 13. Industry Structure

Các block có correlation mạnh:

```text
Real Estate
     ↕
Construction / Materials
     ↕
Industrial Goods / Services
     ↕
Basic Resources
```

Approximate correlations:

```text
Real Estate ↔ Construction/Materials       ≈ 0.71
Construction ↔ Industrial Goods/Services  ≈ 0.63
Construction ↔ Basic Resources            ≈ 0.61
Real Estate ↔ Basic Resources              ≈ 0.60
Financial Services ↔ Construction/RE       ≈ 0.51
```

Các kết quả này rất hữu ích cho portfolio exposure/risk.

---

# 14. Industry Lead-Lag

Close-to-close:

```text
+0.054
t = 3.8
q = 0.006
```

Nhưng open-to-close lag không significant.

Một lần nữa:

```text
Observed statistical relationship
        ≠
Tradable timing edge
```

---

# 15. Industry Momentum

Historical research:

```text
21-session industry momentum
≈ +0.53% / month
t = 2.7
q = 0.019
```

Turnover:

```text
≈66%
```

Sau rough cost:

```text
≈ +0.26%
```

Ban đầu đây là candidate đáng chú ý nhất trong group analysis.

Nhưng robustness yếu:

| Giai đoạn | Return | t |
|---|---:|---:|
| 2006–2010 | +0.41% | 0.7 |
| 2011–2015 | +0.74% | 1.7 |
| 2016–2019 | +0.64% | 2.6 |
| 2020–2023 | +0.21% | 0.65 |

Bỏ 5 tháng tốt nhất:

```text
+0.31%
```

Điều này đã cho thấy effect khá fragile.

---

# 16. Industry Momentum Validation

Preregistration hash:

```text
da8ff1d0750524751a713af792516545b581fe6663dfa2e9dbd95cad55fe0b94
```

Validation:

```text
Jan 2024 – Nov 2025
n = 23
```

### 21-session

```text
Mean spread = -0.18% / month
t = -0.53
p = 0.60
Turnover = 0.65
Net = -0.44%
```

### 63-session

```text
Mean spread = -0.44% / month
t = -1.24
p = 0.23
Net = -0.62%
```

### Decision

```text
FAIL
```

Không đổi parameter để cứu hypothesis.

Không reuse validation period.

Đây là một trong những điểm mạnh nhất của research workflow.

---

# 17. Order-Imbalance Validation

Validation:

```text
Jan 2024 – Dec 2025
```

Preregistration hash:

```text
6fe6d425...
```

## C1 — order_imbalance_d10

```text
17,093 events
Pattern mean = +0.05%
Universe      = -0.42%
Lift          = +0.47%
t             = 4.36
q             = 3.2e-05
After cost    = -0.35%
```

### Decision

```text
FAIL
```

---

## C1b — No limit

```text
Lift       = +0.53%
t          = 4.73
q          = 1.2e-05
After cost = -0.29%
```

### Decision

```text
FAIL
```

---

## C2 — Momentum10 d10

```text
Lift       = +0.48%
t          = 1.97
q          = 0.049
After cost = -0.34%
```

### Decision

```text
FAIL
```

---

## C3 — Drop3 + Volume2 + Sellers

```text
50 events
34 dates
Lift = -5.16%
t = -3.84
q = 7.2e-04
```

Đây là avoid signal đáng chú ý, nhưng sample nhỏ nên chưa nên coi là trading rule mạnh.

---

# 18. Order-Imbalance — Insight quan trọng

Order imbalance cho thấy:

```text
Predictive Information = YES
Economic Value          = NO
Standalone Strategy     = NO
```

Do đó không nên đơn giản xóa feature.

Nó có thể được dùng sau này như:

- ranking feature
- interaction feature
- regime-conditioned feature
- portfolio filter
- risk-management feature

Đây là lý do rất mạnh để xây Interaction Engine.

---

# 19. Portfolio Backtest

Holdout:

```text
Jan 5 2026 – Oct 2 2026
184 sessions
1e9 VND
```

Primary test:

> Beat random controls >=19/20.

Observed:

```text
5/20
```

### Decision

```text
FAIL
```

Secondary:

> Total return after costs > 0.

Observed:

```text
-21.0%
```

### Decision

```text
FAIL
```

---

# 20. Historical vs Holdout

## 2024–2025 — 1e9 VND

```text
Strategy       -2.9%
Random median  -2.9%
Beat random    10/20
Equal weight   +17.4%
VNINDEX        +57.7%
Max DD         -21.3%
Exposure        92%
Turnover/year   33
```

## 2024–2025 — 10e9 VND

```text
Strategy       -7.2%
Random median  -1.4%
Beat random     6/20
Max DD         -13.6%
Exposure        37%
Turnover/year   14
```

## 2026 Holdout — 1e9 VND

```text
Strategy       -21.0%
Random median  -18.9%
Beat random     5/20
Equal weight   -12.3%
VNINDEX         -2.8%
Max DD         -26.1%
Exposure        92%
Turnover/year   36
```

## 2026 Holdout — 10e9 VND

```text
Strategy        -9.6%
Random median  -13.1%
Beat random    15/20
Max DD         -14.1%
Exposure        41%
Turnover/year   17
```

Chưa đủ evidence để tuyên bố có alpha bền vững.

---

# 21. In-Sample Backtest

Historical result:

```text
2007-07 → 2023
CAGR = 14.3%
Beat random = 20/20
```

Nhưng strategy đã được lựa chọn từ:

```text
30 features
24 variants
```

Do đó kết quả in-sample có selection bias rất lớn.

Holdout đã làm đúng nhiệm vụ:

> Kiểm tra xem historical performance có thực sự sống sót trong tương lai hay không.

---

# 22. Thành công lớn về methodology

Project đã chứng minh được khả năng:

```text
Tìm hypothesis
      ↓
Test
      ↓
Validation
      ↓
Phát hiện không survive
      ↓
Đóng hypothesis
```

Mục tiêu của quant research system nên là:

```text
Correct research decisions
```

chứ không phải:

```text
Maximum profitable backtests
```

---

# 23. Kiến trúc mục tiêu

Kiến trúc đề xuất:

```text
                     DATA
                       ↓
                 FEATURE ENGINE
                       ↓
              ┌────────┴────────┐
              ↓                 ↓
         FACTOR ENGINE     REGIME ENGINE
              ↓                 ↓
              └────────┬────────┘
                       ↓
                INTERACTION ENGINE
                       ↓
                HYPOTHESIS ENGINE
                       ↓
              PATTERN / EVENT STUDY
                       ↓
             ECONOMIC VALIDATION
                       ↓
               STRATEGY ENGINE
                       ↓
             PORTFOLIO CONSTRUCTION
                       ↓
               EXPOSURE / RISK
                       ↓
                  BACKTEST
                       ↓
                 HOLDOUT
                       ↓
              RESEARCH DECISION
                       ↓
                FORWARD TRACKING
```

---

# 24. Factor Engine

Đề xuất:

```text
src/quant_research/factors/
```

Initial factors:

- Momentum
- Value
- Size
- Liquidity
- Volatility
- Foreign flow
- Order imbalance
- Volume
- Quality

Pipeline chuẩn:

```text
Raw Feature
    ↓
Winsorize
    ↓
Cross-sectional Rank
    ↓
Z-score
    ↓
Factor Score
```

Output chuẩn:

```text
factor_value
factor_rank
factor_zscore
factor_bucket
factor_neutralized
```

Điều này sẽ tốt hơn rất nhiều so với việc mỗi signal có một implementation riêng.

---

# 25. Regime Engine

Đề xuất:

```text
src/quant_research/regimes/
```

Các regime ban đầu:

### Market Direction

```text
Bull
Bear
Sideways
```

### Volatility

```text
Low
Normal
High
```

### Risk

```text
Risk-on
Neutral
Risk-off
```

### Liquidity

```text
High
Normal
Low
```

Sau đó có thể hỏi:

```text
Momentum có hiệu quả trong Bull market không?

Order imbalance có hiệu quả hơn khi volume cao không?

Foreign flow có quan trọng hơn trong Risk-off không?
```

---

# 26. Interaction Engine

Đề xuất:

```text
src/quant_research/interactions/
```

Ví dụ:

```text
order_imbalance × momentum
foreign_flow × volume
momentum × market_regime
foreign_flow × industry_momentum
volume × volatility
```

Câu hỏi cốt lõi:

> Feature A có predictive hơn khi điều kiện B xảy ra hay không?

Đây có thể là hướng nghiên cứu quan trọng hơn việc tiếp tục tìm standalone signal.

Nhưng Interaction Research làm số lượng hypothesis tăng rất nhanh, nên bắt buộc phải có:

- preregistration
- multiple-testing control
- FDR
- holdout

---

# 27. Exposure Engine

Đây là một cơ hội rất đáng đầu tư.

Ví dụ:

```text
SSI
HCM
VND
```

nhìn như 3 positions.

Nhưng thực tế có thể gần như:

```text
1 broker/financial exposure
```

Exposure Engine nên báo cáo:

```text
Industry exposure
Factor exposure
Cluster exposure
Market beta
Liquidity exposure
Volatility exposure
Concentration
Effective number of bets
```

Đây có thể tạo ra giá trị thực tế lớn hơn việc tiếp tục nghiên cứu pair trading.

---

# 28. Cross-Stock Module — Vai trò mới

Nên chuyển trọng tâm từ:

```text
Prediction
```

sang:

```text
Structure + Risk
```

Các chức năng chính:

- peer groups
- dynamic clusters
- correlation structure
- industry structure
- factor similarity
- concentration
- diversification
- co-movement

---

# 29. Research Registry

Nên có một registry trung tâm:

```text
research_id
hypothesis_id
feature_version
dataset_version
strategy_version
preregistration_hash
code_commit
research_period
validation_period
holdout_period
status
decision
metrics
```

State machine:

```text
DRAFT
PREREGISTERED
RESEARCH
CANDIDATE
VALIDATION
HOLDOUT
VALIDATED
ACTIVE
FAILED
EXPIRED
```

Đây nên trở thành software primitive thực sự.

---

# 30. Standard Research Result

Nên có một result object chung:

```python
ResearchResult(
    hypothesis_id=...,
    dataset_version=...,
    feature_version=...,
    strategy_version=...,
    code_commit=...,
    period=...,
    n_events=...,
    effect=...,
    t_stat=...,
    p_value=...,
    q_value=...,
    turnover=...,
    gross_return=...,
    transaction_cost=...,
    net_return=...,
    benchmark_return=...,
    decision=...,
)
```

Object này có thể dùng chung cho:

- event studies
- pattern discovery
- group analysis
- factor research
- backtests
- cross-stock research

---

# 31. Multiple Testing

Project đã sử dụng BH/FDR ở các research quan trọng.

Nên biến thành policy cấp platform.

Mỗi research family cần định nghĩa:

```text
hypothesis family
number of tests
primary test
secondary tests
correction method
decision threshold
```

Không được:

```text
100 tests
↓
tìm 3 cái p < 0.05
↓
chỉ report 3 cái đó
```

Registry phải lưu cả failure.

---

# 32. Economic Validation Layer

Pipeline chuẩn nên là:

```text
Statistical Signal
       ↓
Effect Size
       ↓
Cost Model
       ↓
Turnover
       ↓
Liquidity
       ↓
Capacity
       ↓
Benchmark Relative
       ↓
Portfolio Construction
       ↓
Decision
```

Không nên cho signal advance chỉ vì:

```text
p < 0.05
```

---

# 33. Transaction Cost Model

Hiện research thường dùng rough assumption khoảng:

```text
0.4% round trip
```

Đây là screening tốt nhưng về lâu dài nên model:

```text
commission
tax
spread
slippage
market impact
liquidity
turnover
position size
```

Cost nên phụ thuộc vào trade thực tế.

---

# 34. Benchmarking

Strategy trong tương lai nên so với:

```text
VNINDEX
Universe Equal-weight
Universe Value-weight
Random Portfolio
Sector-neutral Control
Market-beta-neutral Control
```

Một strategy kiếm được tiền chưa chắc đã có alpha.

Câu hỏi quan trọng là:

> Strategy tạo thêm bao nhiêu giá trị so với việc đơn giản nắm giữ market/universe?

---

# 35. Portfolio Construction

Nên tách rõ:

```text
Signal
```

và:

```text
Portfolio Construction
```

Pipeline:

```text
Signal Score
    ↓
Eligibility
    ↓
Ranking
    ↓
Position Sizing
    ↓
Exposure Constraints
    ↓
Turnover Constraints
    ↓
Liquidity Constraints
    ↓
Portfolio
```

Các constraint nên hỗ trợ:

```text
max_position_weight
max_sector_weight
max_cluster_weight
max_turnover
min_liquidity
beta_target
volatility_target
gross_exposure
net_exposure
```

---

# 36. ML Policy

Không nên vội đưa ML vào ngay.

Trước tiên cần hoàn thiện:

- Factor Engine
- Regime Engine
- Interaction Engine
- Portfolio Construction
- Economic Validation
- Reproducibility

Sau đó ML mới trở thành một model family/hypothesis family.

Nguyên tắc:

> ML là một model class, không phải sự thay thế cho research design.

Không nên làm kiểu:

```text
50 features
↓
XGBoost
↓
Backtest
↓
Profit
```

mà không có protocol được định trước.

---

# 37. Reproducibility

Một research run quan trọng nên reproducible từ:

```text
Git commit
+
Dataset version
+
Feature version
+
Hypothesis version
+
Strategy version
+
Configuration
```

Report nên chứa:

```text
run timestamp
commit SHA
data cutoff
research period
validation period
holdout period
configuration hash
preregistration hash
```

Lý tưởng nhất:

```text
run_id
```

có thể truy ngược toàn bộ kết quả.

---

# 38. Documentation Architecture

Documentation hiện tại tốt nhưng nên chuẩn hóa:

```text
docs/
├── research/
│   ├── registry/
│   ├── hypotheses/
│   ├── validations/
│   ├── holdouts/
│   └── results/
├── architecture/
├── methodology/
├── data/
└── operations/
```

Một research project lớn có thể theo:

```text
01_hypothesis.md
02_preregistration.md
03_research.md
04_validation.md
05_holdout.md
06_decision.md
```

---

# 39. Roadmap đề xuất

## Phase 1 — Research Registry
**Priority: Rất cao**

Xây:

```text
research_registry
research_runs
research_results
hypothesis_status
```

Mục tiêu:

> Biến scientific workflow thành một tính năng chính thức của software.

## Phase 2 — Factor Engine
**Priority: Rất cao**

Chuẩn hóa các factor và normalization.

## Phase 3 — Regime Engine
**Priority: Cao**

Xây market trend, volatility, liquidity, risk regimes.

## Phase 4 — Interaction Engine
**Priority: Cao**

Nghiên cứu conditional relationship.

## Phase 5 — Exposure Engine
**Priority: Cao**

Industry/factor/cluster exposure và effective bets.

## Phase 6 — Portfolio Construction
**Priority: Cao**

Tách signal generation khỏi portfolio implementation.

## Phase 7 — Advanced Research / ML
**Priority: Sau**

Chỉ triển khai sau khi các layer trên ổn định.

---

# 40. Project đang mạnh ở đâu?

### 1. Research discipline

Có khả năng loại bỏ hypothesis.

### 2. Event studies

Phân biệt predictive effect và economic value.

### 3. Cross-sectional research

Có khả năng phân tích stock/industry relationships.

### 4. Forward validation

Có sự phân tách research / validation / holdout.

### 5. Reproducibility

Preregistration hash, run ID và result documents đang đi đúng hướng.

### 6. Data architecture

Crawler → Warehouse → Research là kiến trúc hợp lý.

---

# 41. Điểm yếu hiện tại

Các khoảng trống lớn nhất:

1. **Factor layer** — chưa đủ chuẩn hóa.
2. **Regime layer** — signal chủ yếu được đánh giá unconditional.
3. **Interaction layer** — chưa có hệ thống nghiên cứu conditional relationship.
4. **Exposure layer** — cross-stock structure chưa được chuyển hoàn toàn thành portfolio risk.
5. **Research registry** — lifecycle cần trở thành software primitive.
6. **Portfolio abstraction** — signal và implementation cần tách rõ hơn.
7. **Economic validation** — cost, capacity, liquidity và benchmark cần chuẩn hóa.

---

# 42. Định hướng chiến lược

Project không nên trở thành:

> Một kho khổng lồ các indicator.

Mà nên trở thành:

> **Một quantitative research operating system cho thị trường chứng khoán Việt Nam.**

Câu hỏi trung tâm không nên chỉ là:

```text
Nên mua cổ phiếu nào?
```

mà là:

```text
Hypothesis nào về thị trường Việt Nam thực sự survive
qua quá trình kiểm định out-of-sample nghiêm ngặt,
và nó chỉ hoạt động trong điều kiện nào?
```

Đây là research product mạnh hơn rất nhiều.

---

# 43. Kiến trúc dài hạn

```text
                         DATA
                           ↓
                   DATA WAREHOUSE
                           ↓
                    FEATURE ENGINE
                           ↓
             ┌─────────────┼─────────────┐
             ↓             ↓             ↓
         FACTORS        REGIMES      CROSS-SECTION
             │             │             │
             └─────────────┼─────────────┘
                           ↓
                   INTERACTION ENGINE
                           ↓
                    HYPOTHESIS ENGINE
                           ↓
                 PATTERN / EVENT STUDY
                           ↓
                  STATISTICAL VALIDATION
                           ↓
                    ECONOMIC VALIDATION
                           ↓
                     STRATEGY ENGINE
                           ↓
                 PORTFOLIO CONSTRUCTION
                           ↓
                      EXPOSURE / RISK
                           ↓
                        BACKTEST
                           ↓
                         HOLDOUT
                           ↓
                    RESEARCH DECISION
                           ↓
                    FORWARD TRACKING
```

---

# 44. Kết luận cuối cùng

Điểm ấn tượng nhất của `vn-stock-quant` không phải là project đã tìm được bao nhiêu signal có lợi nhuận.

Mà là project đang chứng minh được khả năng:

```text
Tìm hypothesis
      ↓
Test
      ↓
Validate
      ↓
Phát hiện không survive
      ↓
Đóng hypothesis
```

Cross-stock research cho thấy lead-lag có thể là stale price/opening gap.

Industry momentum cho thấy historical effect có thể biến mất trong forward validation.

Order imbalance cho thấy predictive information có thể tồn tại nhưng economic value biến mất sau cost.

Portfolio backtest cho thấy in-sample performance mạnh không có nghĩa là alpha thực sự tồn tại.

**Đây không phải là thất bại của project.**

Đây chính là bằng chứng cho thấy research framework đang hoạt động đúng.

---

# 45. Khuyến nghị cuối cùng

Không nên ngay lập tức thêm hàng chục trading strategy mới.

Nên dành architectural cycle tiếp theo cho:

```text
1. Research Registry
2. Factor Engine
3. Regime Engine
4. Interaction Engine
5. Exposure Engine
6. Portfolio Construction
7. Standardized Economic Validation
8. Reproducibility Metadata
```

Sau đó mới quay lại alpha discovery.

Research platform thế hệ tiếp theo cần trả lời được:

> Feature này chứa thông tin gì?

> Thông tin đó xuất hiện khi nào?

> Nó có độc lập với các factor khác không?

> Nó có survive transaction cost không?

> Nó có cải thiện portfolio không?

> Nó có survive clean holdout không?

Nếu làm được điều này, `vn-stock-quant` sẽ chuyển từ một **quant research codebase** thành một **quantitative research platform thực sự**.

---

## Project Thesis

> **Xây dựng một hệ thống research giỏi loại bỏ false alpha hơn là tạo ra những backtest đẹp.**
