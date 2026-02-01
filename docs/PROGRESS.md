# Turtle-CANSLIM 구현 진행 상황

> **최종 업데이트**: 2026-02-01 KST  
> **상태**: **완료**  
> **총 Python 파일**: 54개  
> **총 코드 라인**: ~7,200줄  
> **Docker 지원**: ✅

---

## 완료 요약

| Phase | 내용 | 상태 |
|-------|------|------|
| Phase 0 | 프로젝트 초기화 | ✅ 완료 |
| Phase 1 | 데이터 계층 | ✅ 완료 |
| Phase 2 | 분석 엔진 | ✅ 완료 |
| Phase 3 | 리스크 관리 | ✅ 완료 |
| Phase 4 | 주문 실행 | ✅ 완료 |
| Phase 5 | 해외 주식 지원 | ✅ 완료 |
| Phase 6 | 알림 및 모니터링 | ✅ 완료 |
| Phase 7 | TUI (Terminal User Interface) | ✅ 완료 |
| Phase 8 | Docker 배포 | ✅ 완료 |
| 추가 | 테스트, 스크립트, 마이그레이션 | ✅ 완료 |
| 추가 | 문서화 (SETUP.md, DEPLOY.md) | ✅ 완료 |

---

## 완료된 Phase

### Phase 0: 프로젝트 초기화 ✅

| 태스크 | 파일 | 상태 |
|--------|------|------|
| T-001 | 디렉토리 구조 | ✅ 완료 |
| T-001 | `__init__.py` (13개) | ✅ 완료 |
| T-001 | `.gitignore` | ✅ 완료 |
| T-001 | `README.md` | ✅ 완료 |
| T-002 | `pyproject.toml` | ✅ 완료 |
| T-003 | `src/core/config.py` | ✅ 완료 |
| T-003 | `src/core/logger.py` | ✅ 완료 |
| T-003 | `src/core/exceptions.py` | ✅ 완료 |
| T-003 | `config/settings.yaml` | ✅ 완료 |
| T-003 | `.env.example` | ✅ 완료 |

---

### Phase 1: 데이터 계층 ✅

| 태스크 | 파일 | 라인 | 설명 |
|--------|------|------|------|
| T-010 | `src/data/models.py` | ~240 | SQLAlchemy ORM 모델 (Stock, DailyPrice, Fundamental, etc.) |
| T-010 | `src/core/database.py` | ~70 | 비동기 DB 매니저 (AsyncSession) |
| T-011 | `src/data/kis_client.py` | ~270 | 한투 API 클라이언트 |
| T-012 | `src/data/dart_client.py` | ~250 | DART API 클라이언트 |
| T-013 | `src/data/repositories.py` | ~350 | Repository 패턴 (8개 Repository) |

**데이터 모델**:
- `Stock`: 종목 마스터
- `DailyPrice`: 일봉 데이터
- `Fundamental`: 펀더멘탈 데이터
- `CANSLIMScore`: CANSLIM 점수
- `Signal`: 트레이딩 신호
- `Position`: 포지션 (보유 종목)
- `Order`: 주문 내역
- `UnitAllocation`: Unit 할당 현황

---

### Phase 2: 분석 엔진 ✅

#### CANSLIM 지표

| 태스크 | 파일 | 설명 |
|--------|------|------|
| T-020 | `src/screener/criteria/c_earnings.py` | C 지표: 분기 EPS/매출 YoY 성장 (20%/25%+) |
| T-021 | `src/screener/criteria/a_annual.py` | A 지표: 연간 EPS 성장 (20%+, 3년 연속) |
| T-022 | `src/screener/criteria/n_new.py` | N 지표: 신규 요소 (52주 신고가, 신제품, 신경영진) |
| T-023 | `src/screener/criteria/s_supply.py` | S 지표: 수급 (소형주, 거래량 급증, 타이트한 가격) |
| T-024 | `src/screener/criteria/l_leader.py` | L 지표: 상대강도 RS Rating (80+) |
| T-025 | `src/screener/criteria/i_institution.py` | I 지표: 기관 보유 (10%+) |
| T-026 | `src/screener/criteria/m_market.py` | M 지표: 시장 방향 (확인된 상승장) |
| T-027 | `src/screener/scorer.py` | CANSLIM 종합 점수화 |
| T-028 | `src/screener/canslim.py` | CANSLIM 스크리너 메인 |

#### Turtle Trading

| 태스크 | 파일 | 설명 |
|--------|------|------|
| T-030 | `src/signals/atr.py` | ATR(N) 계산 (20일) |
| T-031 | `src/signals/breakout.py` | 돌파 감지 (System 1: 20일, System 2: 55일) |
| T-032 | `src/signals/pyramid.py` | 피라미딩 로직 (0.5N 간격) |
| T-033 | `src/signals/turtle.py` | Turtle 시그널 엔진 메인 |

---

### Phase 3: 리스크 관리 ✅

| 태스크 | 파일 | 설명 |
|--------|------|------|
| T-040 | `src/risk/position_sizing.py` | 2% 룰 기반 포지션 사이징 |
| T-041 | `src/risk/stop_loss.py` | 손절가 계산 (2N vs 8% 중 타이트한 것) |
| T-042 | `src/risk/unit_limits.py` | Unit 한도 관리 (종목당 4, 전체 20) |

**핵심 로직**:
```python
# 손절가: 2N 또는 -8% 중 더 타이트한(높은) 가격
stop_2n = entry_price - (2 * ATR)
stop_8pct = entry_price * 0.92
stop_loss = max(stop_2n, stop_8pct)

# 포지션 크기: 2% 룰 역산
max_risk = account_value * 0.02
risk_per_share = entry_price - stop_loss
quantity = max_risk / risk_per_share
```

---

### Phase 4: 주문 실행 ✅

| 태스크 | 파일 | 설명 |
|--------|------|------|
| T-050 | `src/execution/broker_interface.py` | 브로커 추상 인터페이스 |
| T-051 | `src/execution/paper_broker.py` | 모의투자 브로커 (시뮬레이션) |
| T-052 | `src/execution/live_broker.py` | 실거래 브로커 (한투 API 연동) |
| T-053 | `src/execution/order_manager.py` | 주문 관리자 (진입/청산/피라미딩) |
| T-054 | `src/execution/portfolio.py` | 포트폴리오 상태 관리 |

---

### Phase 5: 해외 주식 지원 ✅

| 태스크 | 파일 | 설명 |
|--------|------|------|
| T-063 | `src/data/sec_edgar_client.py` | SEC EDGAR API 클라이언트 (미국 재무제표) |
| T-064 | `src/data/us_client.py` | 미국 주식 시세 API 클라이언트 (NYSE, NASDAQ) |
| T-065 | `src/screener/us_canslim.py` | 미국 주식 CANSLIM 스크리너 |
| T-066 | `src/data/auto_fetcher.py` | 자동 데이터 수집/갱신 관리 (pykrx, yfinance, DART 배치, SEC EDGAR) |
| T-067 | `scripts/fetch_data.py` | 데이터 수집 CLI 스크립트 |

**AutoDataFetcher 기능**:
- `ensure_data(market)` — 데이터 존재 여부 확인 → 없으면 자동 수집
- `is_data_stale(market)` — 주말 보정 포함 데이터 신선도 확인
- `fetch_and_store(market)` — 전체 종목 초기 로드 (종목 목록 + 1년 일봉)
- `update_prices(market)` — 증분 업데이트 (마지막 수집일 이후)
- `fetch_krx_financials()` — pykrx + DART 배치/개별 재무제표 수집
- `update_us_financials()` — yfinance 기반 미국 재무 업데이트
- `fetch_market_indices(market)` — KOSPI/S&P 500 지수 데이터 수집
- `update_stock_metadata(market)` — 유통주식수, 기관보유 메타데이터 갱신

**SEC EDGAR 클라이언트 기능**:
- Ticker → CIK 변환 (company_tickers.json)
- Company Facts 조회 (XBRL companyfacts API)
- 10-K (연간) / 10-Q (분기) 재무제표 추출
- EPS, Revenue, Net Income, ROE 파싱
- Rate Limiting (10 req/s)

**US 시세 클라이언트 기능**:
- 미국 주식 현재가 조회
- 미국 주식 일봉 데이터
- 미국 주식 주문 실행 (시장가)

**US CANSLIM 스크리너 기능**:
- SEC EDGAR 데이터로 C, A 지표 평가
- 한투 해외 API로 N, S, L 지표 평가
- `get_screener()` 팩토리 함수 (시장별 스크리너 자동 선택)

---

### Phase 6: 알림 및 모니터링 ✅

| 태스크 | 파일 | 설명 |
|--------|------|------|
| T-070 | `src/notification/telegram_bot.py` | Telegram 알림 봇 |
| T-071 | `src/core/scheduler.py` | APScheduler 기반 스케줄러 |

**알림 종류**:
- 시그널 발생 알림
- 주문 체결 알림
- 일일 리포트
- 에러 알림

---

### Phase 7: TUI (Terminal User Interface) ✅

| 태스크 | 파일 | 설명 |
|--------|------|------|
| T-080 | `src/tui/app.py` | Textual 기반 메인 TUI 앱 (~590줄) |
| T-080 | `src/tui/__init__.py` | 패키지 초기화 |
| T-080 | `src/tui/screens/__init__.py` | 화면 모듈 |
| T-080 | `src/tui/widgets/__init__.py` | 위젯 모듈 |
| T-080 | `scripts/run_tui.py` | TUI 실행 스크립트 |

**TUI 기능**:
- **Portfolio 탭**: 보유 포지션 테이블 (종목, 수량, 진입가, 현재가, 손익, Units, 손절가)
- **Candidates 탭**: CANSLIM 후보 종목 (점수, 각 지표 통과 여부, RS Rating, EPS 성장률)
- **Signals 탭**: 트레이딩 시그널 히스토리 (시간, 종목, 유형, 시스템, 가격, ATR, 상태)
- **Settings 탭**: 현재 설정값 확인 (CANSLIM, Turtle, Risk 파라미터, API 상태)
- **실시간 로그 패널**: 작업 진행 상황 실시간 표시

**키보드 단축키**:
| 키 | 기능 |
|----|------|
| `R` | 데이터 새로고침 |
| `S` | CANSLIM 스크리닝 실행 |
| `T` | 트레이딩 사이클 실행 |
| `D` | 다크/라이트 모드 전환 |
| `1-4` | 탭 전환 |
| `Q` | 종료 |

**실행 방법**:
```bash
python scripts/run_tui.py
# 또는
turtle-tui
```

---

### Phase 8: Docker 배포 ✅

| 태스크 | 파일 | 설명 |
|--------|------|------|
| T-090 | `Dockerfile` | 멀티스테이지 빌드 (Python 3.11-slim) |
| T-090 | `docker-compose.yml` | 전체 스택 (App, PostgreSQL, Redis) |
| T-090 | `.dockerignore` | Docker 빌드 제외 파일 |
| T-090 | `docs/DEPLOY.md` | Vultr VPS 배포 가이드 |

**Docker Compose 서비스**:
- `app`: 메인 트레이딩 봇
- `postgres`: PostgreSQL 15 (Alpine)
- `redis`: Redis 7 (Alpine)
- `screener`: CANSLIM 스크리닝 (프로필)
- `tui`: 터미널 UI (프로필)
- `migrate`: DB 마이그레이션 (프로필)

**주요 기능**:
- 멀티스테이지 빌드로 이미지 크기 최소화
- 헬스체크 포함
- 비루트 사용자 실행 (보안)
- 볼륨 영속화 (DB, Redis)
- 환경변수 기반 설정

**실행 방법**:
```bash
docker compose build
docker compose up -d postgres redis
docker compose run --rm migrate
docker compose up -d
```

---

### 추가 구현 ✅

#### 실행 스크립트

| 파일 | 설명 |
|------|------|
| `scripts/run_screener.py` | CANSLIM 스크리닝 CLI |
| `scripts/run_trading.py` | 자동 트레이딩 실행 CLI |
| `scripts/run_backtest.py` | 백테스트 실행 CLI |
| `scripts/run_tui.py` | TUI 실행 스크립트 |
| `scripts/fetch_data.py` | 데이터 수집 CLI (AutoDataFetcher 호출) |

#### 테스트

| 디렉토리 | 파일 | 설명 |
|----------|------|------|
| `tests/` | `conftest.py` | pytest 공통 fixtures |
| `tests/unit/` | `test_canslim.py` | CANSLIM 지표 단위 테스트 |
| `tests/unit/` | `test_turtle.py` | Turtle 시그널 단위 테스트 |
| `tests/unit/` | `test_risk.py` | 리스크 관리 단위 테스트 |
| `tests/integration/` | `test_trading_flow.py` | 전체 트레이딩 플로우 통합 테스트 |

#### DB 마이그레이션

| 파일 | 설명 |
|------|------|
| `alembic.ini` | Alembic 설정 |
| `alembic/env.py` | 마이그레이션 환경 설정 |
| `alembic/script.py.mako` | 마이그레이션 템플릿 |
| `alembic/versions/001_initial_schema.py` | 초기 스키마 마이그레이션 |
| `alembic/versions/002_add_stock_canslim_fields.py` | Stock 테이블 필드 추가 (shares_outstanding, institutional_*) |

#### 문서화

| 파일 | 설명 |
|------|------|
| `docs/DESIGN.md` | 아키텍처 설계 문서 |
| `docs/SPEC.md` | 기술 명세서 |
| `docs/TASKS.md` | 태스크 목록 |
| `docs/PROGRESS.md` | 진행 상황 (이 문서) |
| `docs/SETUP.md` | 사용자 설정 가이드 |
| `docs/DEPLOY.md` | Vultr 배포 가이드 |

---

## 프로젝트 구조

```
turtle-canslim/
├── docs/
│   ├── DESIGN.md        # 설계 문서
│   ├── SPEC.md          # 기술 명세서
│   ├── TASKS.md         # 태스크 목록
│   ├── PROGRESS.md      # 진행 상황 (이 문서)
│   └── SETUP.md         # 사용자 설정 가이드
├── src/
│   ├── tui/             # TUI (Terminal User Interface)
│   │   ├── app.py       # Textual 메인 앱
│   │   ├── screens/     # 화면 모듈
│   │   └── widgets/     # 위젯 모듈
│   ├── core/            # 공통 모듈
│   │   ├── config.py    # Pydantic Settings
│   │   ├── database.py  # AsyncSession 매니저
│   │   ├── logger.py    # structlog 로깅
│   │   ├── exceptions.py # 커스텀 예외
│   │   └── scheduler.py # APScheduler 스케줄러
│   ├── data/            # 데이터 계층
│   │   ├── models.py    # SQLAlchemy ORM
│   │   ├── kis_client.py # 한투 API (국내)
│   │   ├── us_client.py # 한투 API (해외 시세)
│   │   ├── dart_client.py # DART API (국내 재무제표)
│   │   ├── sec_edgar_client.py # SEC EDGAR (미국 재무제표)
│   │   ├── auto_fetcher.py # 자동 데이터 수집/갱신
│   │   └── repositories.py # Repository 패턴
│   ├── screener/        # CANSLIM 스크리너
│   │   ├── canslim.py   # 국내 스크리너
│   │   ├── us_canslim.py # 미국 스크리너 (SEC EDGAR 사용)
│   │   ├── scorer.py    # 점수화
│   │   └── criteria/    # 7개 지표
│   │       ├── c_earnings.py
│   │       ├── a_annual.py
│   │       ├── n_new.py
│   │       ├── s_supply.py
│   │       ├── l_leader.py
│   │       ├── i_institution.py
│   │       └── m_market.py
│   ├── signals/         # Turtle Trading
│   │   ├── turtle.py    # 메인 엔진
│   │   ├── atr.py       # ATR 계산
│   │   ├── breakout.py  # 돌파 감지
│   │   └── pyramid.py   # 피라미딩
│   ├── risk/            # 리스크 관리
│   │   ├── position_sizing.py
│   │   ├── stop_loss.py
│   │   └── unit_limits.py
│   ├── execution/       # 주문 실행
│   │   ├── broker_interface.py
│   │   ├── paper_broker.py
│   │   ├── live_broker.py
│   │   ├── order_manager.py
│   │   └── portfolio.py
│   └── notification/    # 알림
│       └── telegram_bot.py
├── tests/
│   ├── conftest.py      # pytest fixtures
│   ├── unit/            # 단위 테스트
│   │   ├── test_canslim.py
│   │   ├── test_turtle.py
│   │   └── test_risk.py
│   └── integration/     # 통합 테스트
│       └── test_trading_flow.py
├── scripts/
│   ├── run_screener.py  # 스크리닝 실행
│   ├── run_trading.py   # 트레이딩 실행
│   ├── run_backtest.py  # 백테스트 실행
│   ├── run_tui.py       # TUI 실행
│   └── fetch_data.py    # 데이터 수집 CLI
├── alembic/
│   ├── env.py           # 마이그레이션 환경
│   ├── script.py.mako   # 마이그레이션 템플릿
│   └── versions/        # 마이그레이션 버전
│       ├── 001_initial_schema.py
│       └── 002_add_stock_canslim_fields.py
├── config/
│   └── settings.yaml
├── .env.example
├── .gitignore
├── .dockerignore
├── pyproject.toml
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 핵심 설정값 (확정)

```yaml
# CANSLIM 기준
canslim:
  c_eps_growth_min: 0.20      # EPS 20% 이상 (YoY)
  c_revenue_growth_min: 0.25  # 매출 25% 이상 (YoY)
  a_eps_growth_min: 0.20      # 연간 EPS 20% 이상
  l_rs_min: 80                # RS Rating 80 이상

# Turtle Trading
turtle:
  system1_entry_period: 20    # System 1 (20일 돌파)
  system2_entry_period: 55    # System 2 (55일 돌파)
  pyramid_unit_interval: 0.5  # 0.5N 간격 피라미딩

# 리스크 관리
risk:
  risk_per_unit: 0.02         # 2% 룰
  max_units_per_stock: 4      # 종목당 최대 4 Units
  max_units_total: 20         # 포트폴리오 최대 20 Units
  stop_loss_atr_multiplier: 2 # 2N 손절
  stop_loss_max_percent: 0.08 # 8% 손절 (둘 중 타이트한 것)
```

---

## 설치 및 실행

```bash
# 의존성 설치
pip install -e ".[dev]"

# 환경변수 설정
cp .env.example .env
# .env 파일 편집

# DB 마이그레이션
alembic upgrade head

# 스크리닝 실행
python scripts/run_screener.py

# 트레이딩 실행 (모의투자)
python scripts/run_trading.py --mode paper

# 백테스트 실행
python scripts/run_backtest.py
```

자세한 설정 방법은 [SETUP.md](./SETUP.md)를 참조하세요.

---

## 참고 사항

### LSP 에러
현재 표시되는 LSP 에러는 의존성이 설치되지 않아서 발생합니다:
- `pydantic`, `pydantic_settings`
- `sqlalchemy`
- `structlog`
- `python_kis`
- `httpx`

`pip install -e ".[dev]"` 실행 후 해결됩니다.

### 제약사항 (MUST NOT)
- Heat 개념 사용 금지 → Unit 한도로 대체
- 고정 최대 종목 수 사용 금지 → Unit 한도에서 자동 계산
- CANSLIM C 지표 통과 판정은 EPS만 (매출은 보조 지표로 기록)
- QoQ(직전 분기) 비교 금지 → YoY(전년 동기) 비교 필수
- System 1 또는 System 2 중 하나만 선택 금지 → 둘 다 병행 사용

---

## 완료 일자

| Phase | 완료일 |
|-------|--------|
| Phase 0 | 2026-01-20 |
| Phase 1 | 2026-01-20 |
| Phase 2 | 2026-01-20 |
| Phase 3 | 2026-01-20 |
| Phase 4 | 2026-01-20 |
| Phase 5 | 2026-01-20 |
| Phase 6 | 2026-01-20 |
| Phase 7 (TUI) | 2026-01-21 |
| Phase 8 (Docker) | 2026-01-21 |
| 문서화 | 2026-01-21 |
