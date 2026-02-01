# DB 데이터 확인 가이드

## 접속 정보

```bash
# Docker PostgreSQL 컨테이너
docker exec -it turtle-postgres psql -U turtle -d turtle_canslim

# 또는 외부 접속
psql postgresql://turtle:turtle_secret_2024@localhost:5432/turtle_canslim
```

---

## 테이블 구조

### stocks (종목 마스터)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | integer PK | 자동 증가 |
| symbol | varchar(20) UNIQUE | 종목코드 (KRX: `000120`, US: `AAPL`) |
| name | varchar(100) | 종목명 |
| market | varchar(10) | `KOSPI`, `KOSDAQ`, `NYSE`, `NASDAQ` |
| sector | varchar(50) | 섹터 (US만 수집) |
| industry | varchar(50) | 업종 (US만 수집) |
| is_active | boolean | 활성 여부 |
| created_at | timestamp | 생성일 |
| updated_at | timestamp | 수정일 |

### daily_prices (일별 가격)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | integer PK | 자동 증가 |
| stock_id | integer FK → stocks | 종목 참조 |
| date | timestamp | 거래일 |
| open / high / low / close | numeric(18,4) | OHLC |
| volume | integer | 거래량 |

UNIQUE 제약: `(stock_id, date)`

### fundamentals (재무제표)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | integer PK | 자동 증가 |
| stock_id | integer FK → stocks | 종목 참조 |
| fiscal_year | integer | 회계연도 (2024, 2025 등) |
| fiscal_quarter | integer | 분기 (1~4), NULL=연간 |
| revenue | numeric(20,2) | 매출액 |
| operating_income | numeric(20,2) | 영업이익 |
| net_income | numeric(20,2) | 순이익 |
| eps | numeric(18,4) | 주당순이익 |
| total_assets | numeric(20,2) | 총자산 |
| total_equity | numeric(20,2) | 총자본 |
| roe | numeric(10,4) | 자기자본이익률 |
| created_at | timestamp | 생성일 |

UNIQUE 제약: `(stock_id, fiscal_year, fiscal_quarter)`

### canslim_scores (CANSLIM 점수)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | integer PK | 자동 증가 |
| stock_id | integer FK → stocks | 종목 참조 |
| date | timestamp | 스크리닝 일자 |
| c_score ~ m_score | boolean | 각 조건 통과 여부 (7개) |
| total_score | integer | 총 점수 (0~7) |
| rs_rating | integer | 상대강도 등급 |
| c_eps_growth | numeric | EPS 성장률 |
| c_revenue_growth | numeric | 매출 성장률 |
| a_eps_growth | numeric | 연간 EPS 성장률 |
| is_candidate | boolean | 후보 종목 여부 |
| created_at | timestamp | 생성일 |

### signals (매매 시그널)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| stock_id | integer FK | 종목 |
| timestamp | timestamp | 시그널 발생 시점 |
| signal_type | varchar(20) | `ENTRY_S1`, `ENTRY_S2`, `EXIT_S1`, `EXIT_S2`, `STOP_LOSS`, `PYRAMID` |
| system | integer | Turtle 시스템 번호 (1 또는 2) |
| price | numeric | 시그널 가격 |
| atr_n | numeric | ATR(N) 값 |

### positions (포지션)
entry_date, entry_price, quantity, units, stop_loss_price, status(`OPEN`/`CLOSED`), exit 관련 필드, pnl

### orders (주문)
order_type(`BUY`/`SELL`), order_method(`MARKET`/`LIMIT`), status(`PENDING`/`FILLED`/...), broker_order_id

### unit_allocations (유닛 배분)
total_units, available_units, sector_allocations(JSON text)

---

## 자주 쓰는 조회 쿼리

### 전체 현황 파악
```sql
-- 테이블별 레코드 수
SELECT 'stocks' as tbl, COUNT(*) FROM stocks
UNION ALL SELECT 'daily_prices', COUNT(*) FROM daily_prices
UNION ALL SELECT 'fundamentals', COUNT(*) FROM fundamentals
UNION ALL SELECT 'canslim_scores', COUNT(*) FROM canslim_scores
UNION ALL SELECT 'signals', COUNT(*) FROM signals
UNION ALL SELECT 'positions', COUNT(*) FROM positions;
```

### 종목 확인
```sql
-- 마켓별 종목 수
SELECT market, COUNT(*) FROM stocks GROUP BY market ORDER BY market;

-- 전체 종목 목록
SELECT id, symbol, name, market, sector FROM stocks ORDER BY market, symbol;

-- 특정 종목 검색
SELECT * FROM stocks WHERE symbol = 'AAPL';
SELECT * FROM stocks WHERE name LIKE '%삼성%';
```

### 가격 데이터 확인
```sql
-- 마켓별 가격 데이터 범위
SELECT s.market, COUNT(*), MIN(dp.date), MAX(dp.date)
FROM daily_prices dp JOIN stocks s ON dp.stock_id = s.id
GROUP BY s.market;

-- 특정 종목 최근 가격
SELECT dp.date, dp.open, dp.high, dp.low, dp.close, dp.volume
FROM daily_prices dp JOIN stocks s ON dp.stock_id = s.id
WHERE s.symbol = '005930'
ORDER BY dp.date DESC LIMIT 10;

-- 가격 데이터 없는 종목
SELECT s.symbol, s.name, s.market
FROM stocks s LEFT JOIN daily_prices dp ON s.id = dp.stock_id
WHERE dp.id IS NULL;
```

### 재무제표 확인
```sql
-- 종목별 재무제표 보유 현황
SELECT s.symbol, s.name, s.market,
       COUNT(*) as periods,
       MIN(f.fiscal_year) as from_year,
       MAX(f.fiscal_year) as to_year
FROM fundamentals f JOIN stocks s ON f.stock_id = s.id
GROUP BY s.symbol, s.name, s.market
ORDER BY s.market, s.symbol;

-- 특정 종목 분기별 재무제표
SELECT f.fiscal_year, f.fiscal_quarter, f.revenue, f.net_income, f.eps, f.roe
FROM fundamentals f JOIN stocks s ON f.stock_id = s.id
WHERE s.symbol = '005930'
ORDER BY f.fiscal_year DESC, f.fiscal_quarter DESC;

-- 재무제표 없는 종목
SELECT s.symbol, s.name, s.market
FROM stocks s LEFT JOIN fundamentals f ON s.id = f.stock_id
WHERE f.id IS NULL;
```

### CANSLIM 스크리닝 결과
```sql
-- 최근 스크리닝 결과 (점수 높은 순)
SELECT s.symbol, s.name, s.market,
       cs.total_score, cs.is_candidate,
       cs.c_score, cs.a_score, cs.n_score, cs.s_score,
       cs.l_score, cs.i_score, cs.m_score,
       cs.created_at
FROM canslim_scores cs JOIN stocks s ON cs.stock_id = s.id
ORDER BY cs.total_score DESC, cs.created_at DESC
LIMIT 20;

-- 후보 종목만
SELECT s.symbol, s.name, s.market, cs.total_score
FROM canslim_scores cs JOIN stocks s ON cs.stock_id = s.id
WHERE cs.is_candidate = true
ORDER BY cs.total_score DESC;
```

### 데이터 품질 확인
```sql
-- fiscal_quarter가 NULL인 재무제표 (연간 합산 데이터)
SELECT s.symbol, f.fiscal_year, f.revenue, f.net_income
FROM fundamentals f JOIN stocks s ON f.stock_id = s.id
WHERE f.fiscal_quarter IS NULL
ORDER BY s.symbol, f.fiscal_year;

-- 종목별 가격 데이터 건수
SELECT s.symbol, s.market, COUNT(dp.id) as price_count
FROM stocks s LEFT JOIN daily_prices dp ON s.id = dp.stock_id
GROUP BY s.symbol, s.market
ORDER BY price_count;
```

---

## Python에서 확인

```python
import asyncio
from src.core.database import get_db_manager
from sqlalchemy import text

async def check():
    db = get_db_manager()
    async with db.session() as s:
        r = await s.execute(text("SELECT market, COUNT(*) FROM stocks GROUP BY market"))
        for row in r.fetchall():
            print(row)

asyncio.run(check())
```

---

## 현재 DB 현황 (2026-01-29 기준)

| 테이블 | 레코드 수 | 비고 |
|--------|----------|------|
| stocks | 87 | KOSPI 40, NASDAQ 21, NYSE 26 |
| daily_prices | 21,644 | KRX 9,800 / US 11,844 |
| fundamentals | 847 | KRX DART 분기별 + US yfinance |
| canslim_scores | 0 | 스크리닝 실행 시 생성 |
| signals | 0 | 트레이딩 시그널 미생성 |
| positions | 0 | 미거래 |
| orders | 0 | 미거래 |

### 가격 데이터 범위
- **KOSPI**: 2025-01-31 ~ 2026-01-29 (약 1년)
- **NASDAQ**: 2025-01-29 ~ 2026-01-29 (약 1년)
- **NYSE**: 2025-01-29 ~ 2026-01-29 (약 1년)
