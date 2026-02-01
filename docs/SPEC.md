# Turtle-CANSLIM 기술 명세서 (SPEC)

> **버전**: 1.1.0  
> **최종 수정**: 2026-02-01  
> **관련 문서**: [DESIGN.md](./DESIGN.md)

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [기술 요구사항](#2-기술-요구사항)
3. [의존성](#3-의존성)
4. [설정 구조](#4-설정-구조)
5. [데이터 모델](#5-데이터-모델)
6. [모듈 명세](#6-모듈-명세)
7. [API 연동 명세](#7-api-연동-명세)
8. [테스트 요구사항](#8-테스트-요구사항)
9. [배포 요구사항](#9-배포-요구사항)

---

## 1. 프로젝트 개요

### 1.1 목적

CANSLIM 펀더멘탈 분석과 Turtle Trading 기술적 분석을 결합한 국내/해외 주식 자동매매 시스템

### 1.2 핵심 기능

| 기능 | 설명 |
|------|------|
| CANSLIM 스크리닝 | 펀더멘탈 기준으로 우량 성장주 필터링 |
| Turtle 시그널 | 돌파 기반 진입/청산 신호 생성 |
| 리스크 관리 | 2% 룰 + Unit 한도 기반 포지션 관리 |
| 자동 주문 | 한국투자증권 API를 통한 자동 매매 |
| 알림 | Telegram을 통한 실시간 알림 |

### 1.3 지원 시장

| 시장 | 거래소 | 우선순위 |
|------|--------|---------|
| 국내 | KRX (KOSPI, KOSDAQ) | Phase 1 |
| 해외 | NYSE, NASDAQ | Phase 2 |

---

## 2. 기술 요구사항

### 2.1 런타임 환경

| 항목 | 요구사항 |
|------|----------|
| Python | 3.11 이상 |
| OS | macOS, Linux (Windows 미지원) |
| 메모리 | 최소 4GB RAM |
| 디스크 | 최소 10GB (데이터 저장용) |

### 2.2 외부 서비스

| 서비스 | 용도 | 필수 여부 |
|--------|------|----------|
| 한국투자증권 Open API | 시세, 주문, 계좌 | 필수 |
| DART OpenAPI | 국내 재무제표 | 필수 |
| PostgreSQL | 데이터 저장 | 필수 |
| Redis | 캐시, 세션 | 선택 |
| Telegram Bot | 알림 | 선택 |

### 2.3 네트워크

| 항목 | 요구사항 |
|------|----------|
| 인터넷 | 안정적인 연결 필수 |
| WebSocket | 실시간 시세용 |
| 방화벽 | 한투 API 도메인 허용 필요 |

---

## 3. 의존성

### 3.1 핵심 의존성

```toml
[project]
name = "turtle-canslim"
version = "0.6.0"
requires-python = ">=3.11"

dependencies = [
    # 한투 API
    "python-kis>=2.1.0",
    
    # 데이터 처리
    "pandas>=2.0.0",
    "numpy>=1.24.0",
    "pykrx>=1.0.0",           # KRX 주가/재무 데이터
    "yfinance>=0.2.0",        # 미국 주가/재무 데이터
    
    # 데이터베이스
    "sqlalchemy>=2.0.0",
    "psycopg[binary]>=3.1.0",
    "alembic>=1.13.0",
    
    # 캐시
    "redis>=5.0.0",
    
    # HTTP
    "httpx>=0.25.0",
    
    # 스케줄링
    "apscheduler>=3.10.0",
    
    # 알림
    "python-telegram-bot>=20.0",
    
    # 설정 & 검증
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "pyyaml>=6.0.0",
    
    # TUI & 터미널
    "textual>=0.40.0",        # TUI 프레임워크
    "rich>=13.0.0",           # 터미널 서식
    
    # 유틸리티
    "python-dotenv>=1.0.0",
    "structlog>=23.0.0",
]
```

### 3.2 개발 의존성

```toml
[project.optional-dependencies]
dev = [
    # 테스트
    "pytest>=7.4.0",
    "pytest-cov>=4.1.0",
    "pytest-asyncio>=0.21.0",
    "pytest-mock>=3.12.0",
    
    # 타입 체크
    "mypy>=1.7.0",
    "pandas-stubs>=2.0.0",
    
    # 린팅
    "ruff>=0.1.0",
    
    # 백테스트
    "backtesting>=0.3.3",
    "vectorbt>=0.25.0",
]
```

---

## 4. 설정 구조

### 4.1 환경 변수

```bash
# .env 파일 구조
# 트레이딩 모드
TRADING_MODE=paper  # paper | live

# 한투 API (모의투자)
KIS_PAPER_APP_KEY=PSxxxxxxxx
KIS_PAPER_APP_SECRET=xxxxxxxx
KIS_PAPER_ACCOUNT=50012345-01

# 한투 API (실거래)
KIS_LIVE_APP_KEY=xxxxxxxx
KIS_LIVE_APP_SECRET=xxxxxxxx
KIS_LIVE_ACCOUNT=12345678-01

# DART API
DART_API_KEY=xxxxxxxx

# 데이터베이스
DATABASE_URL=postgresql://user:pass@localhost:5432/turtle_canslim

# Redis (선택)
REDIS_URL=redis://localhost:6379/0

# Telegram (선택)
TELEGRAM_BOT_TOKEN=xxxxxxxx
TELEGRAM_CHAT_ID=xxxxxxxx
```

### 4.2 설정 파일 (config/settings.yaml)

```yaml
# 트레이딩 설정
trading:
  mode: paper  # paper | live
  market: krx  # krx | us | both

# CANSLIM 기준
canslim:
  c_eps_growth_min: 0.20      # 20%
  c_revenue_growth_min: 0.25  # 25%
  a_eps_growth_min: 0.20      # 20%
  a_min_years: 2              # 최소 2년 데이터 (3년분 EPS = 2개 성장률)
  l_rs_min: 80                # RS 80 이상
  i_institution_min: 0.10     # 기관 10% 이상

# Turtle Trading 설정
turtle:
  system1_entry_period: 20
  system1_exit_period: 10
  system2_entry_period: 55
  system2_exit_period: 20
  atr_period: 20
  pyramid_unit_interval: 0.5  # 0.5N 간격

# 리스크 관리
risk:
  risk_per_unit: 0.02         # 2%
  max_units_per_stock: 4
  max_units_correlated: 10
  max_units_loosely_correlated: 16
  max_units_total: 20
  stop_loss_atr_multiplier: 2  # 2N
  stop_loss_max_percent: 0.08  # 8%

# 스케줄
schedule:
  krx:
    screening_time: "08:00"
    market_open: "09:00"
    market_close: "15:30"
  us:
    screening_time: "21:00"
    market_open: "23:30"
    market_close: "06:00"

# 알림
notification:
  telegram_enabled: true
  notify_on_signal: true
  notify_on_order: true
  notify_on_fill: true
  daily_report: true
```

### 4.3 Pydantic 설정 모델

```python
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from enum import Enum

class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"

class Market(str, Enum):
    KRX = "krx"
    US = "us"
    BOTH = "both"

class CANSLIMConfig(BaseModel):
     c_eps_growth_min: float = 0.20
     c_revenue_growth_min: float = 0.25
     a_eps_growth_min: float = 0.20
     a_min_years: int = 2
     l_rs_min: int = 80
     i_institution_min: float = 0.10

class TurtleConfig(BaseModel):
    system1_entry_period: int = 20
    system1_exit_period: int = 10
    system2_entry_period: int = 55
    system2_exit_period: int = 20
    atr_period: int = 20
    pyramid_unit_interval: float = 0.5

class RiskConfig(BaseModel):
    risk_per_unit: float = 0.02
    max_units_per_stock: int = 4
    max_units_correlated: int = 10
    max_units_loosely_correlated: int = 16
    max_units_total: int = 20
    stop_loss_atr_multiplier: float = 2.0
    stop_loss_max_percent: float = 0.08

class Settings(BaseSettings):
    trading_mode: TradingMode = TradingMode.PAPER
    market: Market = Market.KRX
    
    # API Keys
    kis_paper_app_key: str = ""
    kis_paper_app_secret: str = ""
    kis_paper_account: str = ""
    kis_live_app_key: str = ""
    kis_live_app_secret: str = ""
    kis_live_account: str = ""
    dart_api_key: str = ""
    
    # Database
    database_url: str = ""
    redis_url: str = ""
    
    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    
    # Nested configs
    canslim: CANSLIMConfig = CANSLIMConfig()
    turtle: TurtleConfig = TurtleConfig()
    risk: RiskConfig = RiskConfig()
    
    class Config:
        env_file = ".env"
        env_nested_delimiter = "__"
```

---

## 5. 데이터 모델

### 5.1 데이터베이스 스키마

```python
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Stock(Base):
     """종목 마스터"""
     __tablename__ = "stocks"
     
     id = Column(Integer, primary_key=True)
     symbol = Column(String(20), unique=True, nullable=False)  # 종목코드
     name = Column(String(100), nullable=False)                 # 종목명
     market = Column(String(10), nullable=False)                # KRX, NYSE, NASDAQ
     sector = Column(String(50))                                # 섹터
     industry = Column(String(50))                              # 업종
     shares_outstanding = Column(Integer)                       # 유통주식수
     institutional_ownership = Column(Float)                    # 기관 보유 비율
     institutional_change = Column(Float)                       # 기관 보유 변화
     is_active = Column(Boolean, default=True)
     created_at = Column(DateTime, default=datetime.utcnow)
     updated_at = Column(DateTime, onupdate=datetime.utcnow)

class DailyPrice(Base):
    """일봉 데이터 (TimescaleDB hypertable)"""
    __tablename__ = "daily_prices"
    
    stock_id = Column(Integer, ForeignKey("stocks.id"), primary_key=True)
    date = Column(DateTime, primary_key=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)
    
class Fundamental(Base):
    """펀더멘탈 데이터"""
    __tablename__ = "fundamentals"
    
    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    fiscal_quarter = Column(Integer)  # NULL이면 연간
    
    # 손익계산서
    revenue = Column(Float)
    operating_income = Column(Float)
    net_income = Column(Float)
    eps = Column(Float)
    
    # 재무상태표
    total_assets = Column(Float)
    total_equity = Column(Float)
    
    # 지표
    roe = Column(Float)
    
    created_at = Column(DateTime, default=datetime.utcnow)

class CANSLIMScore(Base):
    """CANSLIM 점수"""
    __tablename__ = "canslim_scores"
    
    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    date = Column(DateTime, nullable=False)
    
    c_score = Column(Boolean)  # 통과 여부
    a_score = Column(Boolean)
    n_score = Column(Boolean)
    s_score = Column(Boolean)
    l_score = Column(Boolean)
    i_score = Column(Boolean)
    m_score = Column(Boolean)
    
    total_score = Column(Integer)  # 통과 개수 (0~7)
    rs_rating = Column(Integer)    # RS Rating (1~99)
    
    c_eps_growth = Column(Float)
    c_revenue_growth = Column(Float)
    a_eps_growth = Column(Float)
    
    is_candidate = Column(Boolean)  # 관심 종목 여부
    created_at = Column(DateTime, default=datetime.utcnow)

class Signal(Base):
    """트레이딩 신호"""
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    
    signal_type = Column(String(20))  # ENTRY_S1, ENTRY_S2, EXIT_S1, EXIT_S2, STOP_LOSS
    system = Column(Integer)          # 1 or 2
    price = Column(Float, nullable=False)
    atr_n = Column(Float)
    
    is_executed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Position(Base):
    """포지션 (보유 종목)"""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    
    entry_date = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    entry_system = Column(Integer)  # 1 or 2
    
    quantity = Column(Integer, nullable=False)
    units = Column(Integer, default=1)  # 현재 Unit 수 (피라미딩)
    
    stop_loss_price = Column(Float)
    stop_loss_type = Column(String(10))  # 2N or 8%
    
    status = Column(String(20), default="OPEN")  # OPEN, CLOSED
    exit_date = Column(DateTime)
    exit_price = Column(Float)
    exit_reason = Column(String(50))  # SYSTEM_EXIT, STOP_LOSS
    
    pnl = Column(Float)  # 실현 손익
    pnl_percent = Column(Float)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

class Order(Base):
    """주문 내역"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True)
    position_id = Column(Integer, ForeignKey("positions.id"))
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    
    order_type = Column(String(10))   # BUY, SELL
    order_method = Column(String(20)) # MARKET, LIMIT
    quantity = Column(Integer, nullable=False)
    price = Column(Float)             # 지정가 (시장가면 NULL)
    
    status = Column(String(20))       # PENDING, FILLED, CANCELLED, FAILED
    filled_quantity = Column(Integer, default=0)
    filled_price = Column(Float)
    
    broker_order_id = Column(String(50))  # 한투 주문번호
    
    created_at = Column(DateTime, default=datetime.utcnow)
    filled_at = Column(DateTime)

class UnitAllocation(Base):
    """Unit 할당 현황"""
    __tablename__ = "unit_allocations"
    
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False)
    
    total_units = Column(Integer, default=0)
    available_units = Column(Integer)
    
    # 섹터별 Unit 집계
    sector_allocations = Column(String(500))  # JSON
    
    created_at = Column(DateTime, default=datetime.utcnow)
```

### 5.2 Pydantic DTO

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class StockDTO(BaseModel):
    symbol: str
    name: str
    market: str
    sector: Optional[str] = None
    
class PriceDTO(BaseModel):
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

class CANSLIMResultDTO(BaseModel):
    stock: StockDTO
    date: datetime
    
    c_passed: bool
    c_eps_growth: float
    c_revenue_growth: float
    
    a_passed: bool
    a_eps_growth: float
    a_roe: float
    
    n_passed: bool
    s_passed: bool
    
    l_passed: bool
    rs_rating: int
    
    i_passed: bool
    institution_ownership: float
    
    m_passed: bool
    market_status: str
    
    total_score: int
    is_candidate: bool

class SignalDTO(BaseModel):
    stock: StockDTO
    signal_type: str  # ENTRY_S1, ENTRY_S2, EXIT_S1, EXIT_S2, STOP_LOSS
    system: int
    price: float
    atr_n: float
    stop_loss_price: float
    position_size: int
    timestamp: datetime

class PositionDTO(BaseModel):
    stock: StockDTO
    entry_date: datetime
    entry_price: float
    entry_system: int
    quantity: int
    units: int
    stop_loss_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_percent: float

class PortfolioDTO(BaseModel):
    total_value: float
    cash: float
    positions: list[PositionDTO]
    total_units: int
    available_units: int
    total_risk: float  # 총 리스크 (%)
```

---

## 6. 모듈 명세

### 6.1 프로젝트 구조

```
turtle-canslim/
├── src/
│   ├── __init__.py
│   │
│   ├── tui/                     # TUI (Terminal User Interface)
│   │   ├── __init__.py
│   │   ├── app.py               # Textual 기반 메인 TUI 앱
│   │   ├── screens/             # 화면 모듈
│   │   └── widgets/             # 위젯 모듈
│   │
│   ├── data/                    # 데이터 계층
│   │   ├── __init__.py
│   │   ├── models.py            # SQLAlchemy ORM 모델
│   │   ├── repositories.py      # Repository 패턴 (DB 접근)
│   │   ├── kis_client.py        # 한투 API 클라이언트 (국내)
│   │   ├── us_client.py         # 한투 API 클라이언트 (해외 시세)
│   │   ├── dart_client.py       # DART API 클라이언트 (배치+개별)
│   │   ├── sec_edgar_client.py  # SEC EDGAR 클라이언트 (미국 재무)
│   │   └── auto_fetcher.py      # 자동 데이터 수집/갱신 관리
│   │
│   ├── screener/                # CANSLIM 스크리너
│   │   ├── __init__.py
│   │   ├── canslim.py           # 국내 CANSLIM 스크리너
│   │   ├── us_canslim.py        # 미국 CANSLIM 스크리너
│   │   ├── criteria/
│   │   │   ├── __init__.py
│   │   │   ├── c_earnings.py    # C: 분기 EPS (핵심), 매출 (보조)
│   │   │   ├── a_annual.py      # A: 다년 평균 EPS 성장
│   │   │   ├── n_new.py         # N: 신규 요소
│   │   │   ├── s_supply.py      # S: 수급
│   │   │   ├── l_leader.py      # L: 상대강도
│   │   │   ├── i_institution.py # I: 기관
│   │   │   └── m_market.py      # M: 시장
│   │   └── scorer.py            # 종합 점수화
│   │
│   ├── signals/                 # Turtle Trading
│   │   ├── __init__.py
│   │   ├── turtle.py            # Turtle 메인 오케스트레이터
│   │   ├── atr.py               # N값 (ATR) 계산
│   │   ├── breakout.py          # 돌파 감지 (S1 필터 포함)
│   │   └── pyramid.py           # 피라미딩 로직
│   │
│   ├── risk/                    # 리스크 관리
│   │   ├── __init__.py
│   │   ├── position_sizing.py   # 포지션 사이징 (2% 룰)
│   │   ├── stop_loss.py         # 손절가 (2N/8%/Trailing/Breakeven)
│   │   └── unit_limits.py       # Unit 한도 관리
│   │
│   ├── execution/               # 주문 실행
│   │   ├── __init__.py
│   │   ├── broker_interface.py  # 브로커 추상 인터페이스 (async)
│   │   ├── paper_broker.py      # 모의투자 (인메모리 시뮬레이션)
│   │   ├── live_broker.py       # 실제투자 (한투 KIS API)
│   │   ├── order_manager.py     # 주문 관리
│   │   └── portfolio.py         # 포트폴리오 상태
│   │
│   ├── notification/            # 알림
│   │   ├── __init__.py
│   │   └── telegram_bot.py
│   │
│   └── core/                    # 공통
│       ├── __init__.py
│       ├── config.py            # Pydantic Settings
│       ├── database.py          # 비동기 DB 매니저 (AsyncSession)
│       ├── scheduler.py         # APScheduler 스케줄러
│       ├── logger.py            # structlog 로깅
│       └── exceptions.py        # 커스텀 예외
│
├── tests/
│   ├── conftest.py              # pytest 공통 fixtures
│   ├── unit/
│   │   ├── test_canslim.py
│   │   ├── test_turtle.py
│   │   └── test_risk.py
│   ├── integration/
│   │   └── test_trading_flow.py
│   └── backtest/
│
├── alembic/                     # DB 마이그레이션
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
│
├── scripts/
│   ├── run_screener.py          # 스크리닝 실행
│   ├── run_trading.py           # 트레이딩 실행
│   ├── run_backtest.py          # 백테스트 실행
│   ├── run_tui.py               # TUI 실행
│   └── fetch_data.py            # 데이터 수집 CLI
│
├── config/
│   ├── settings.yaml
│   └── logging.yaml
│
├── docs/
│   ├── DESIGN.md
│   ├── SPEC.md
│   ├── TASKS.md
│   ├── PROGRESS.md
│   ├── SETUP.md
│   └── DEPLOY.md
│
├── .env.example
├── pyproject.toml
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
└── README.md
```

### 6.2 모듈별 인터페이스

#### 6.2.1 CANSLIM Screener

```python
# src/screener/canslim.py

from typing import List
from ..data.repositories import StockRepository, FundamentalRepository
from .criteria import CEarnings, AAnnual, NNew, SSupply, LLeader, IInstitution, MMarket
from .scorer import CANSLIMScorer

class CANSLIMScreener:
    """CANSLIM 스크리너 메인 클래스"""
    
    def __init__(
        self,
        stock_repo: StockRepository,
        fundamental_repo: FundamentalRepository,
        config: CANSLIMConfig
    ):
        self.stock_repo = stock_repo
        self.fundamental_repo = fundamental_repo
        self.config = config
        
        # 각 지표 초기화
        self.c_criteria = CEarnings(config)
        self.a_criteria = AAnnual(config)
        self.n_criteria = NNew(config)
        self.s_criteria = SSupply(config)
        self.l_criteria = LLeader(config)
        self.i_criteria = IInstitution(config)
        self.m_criteria = MMarket(config)
        self.scorer = CANSLIMScorer()
    
    async def screen(self, market: str = "krx") -> List[CANSLIMResultDTO]:
        """
        전체 스크리닝 실행
        
        Args:
            market: 시장 (krx, us)
        
        Returns:
            CANSLIM 후보 종목 리스트
        """
        pass
    
    async def evaluate_stock(self, symbol: str) -> CANSLIMResultDTO:
        """단일 종목 평가"""
        pass
    
    async def get_candidates(self, min_score: int = 5) -> List[CANSLIMResultDTO]:
        """최소 점수 이상 종목 조회"""
        pass
```

#### 6.2.2 Turtle Signal Engine

```python
# src/signals/turtle.py

from typing import List, Optional
from ..data.repositories import PriceRepository, PositionRepository
from .atr import ATRCalculator
from .breakout import BreakoutDetector
from .pyramid import PyramidManager

class TurtleSignalEngine:
    """Turtle Trading 시그널 엔진"""
    
    def __init__(
        self,
        price_repo: PriceRepository,
        position_repo: PositionRepository,
        config: TurtleConfig
    ):
        self.price_repo = price_repo
        self.position_repo = position_repo
        self.config = config
        
        self.atr_calc = ATRCalculator(config.atr_period)
        self.breakout = BreakoutDetector(config)
        self.pyramid = PyramidManager(config)
    
    async def check_entry_signals(
        self, 
        candidates: List[str]
    ) -> List[SignalDTO]:
        """
        CANSLIM 후보 종목에 대해 진입 신호 확인
        
        Args:
            candidates: CANSLIM 통과 종목 코드 리스트
        
        Returns:
            진입 신호 리스트
        """
        pass
    
    async def check_exit_signals(self) -> List[SignalDTO]:
        """
        보유 포지션에 대해 청산 신호 확인
        
        Returns:
            청산 신호 리스트 (시스템 청산 + 손절)
        """
        pass
    
    async def check_pyramid_signals(self) -> List[SignalDTO]:
        """
        피라미딩 신호 확인
        
        Returns:
            추가 매수 신호 리스트
        """
        pass
```

#### 6.2.3 Risk Manager

```python
# src/risk/position_sizing.py

class PositionSizer:
    """포지션 사이징 계산"""
    
    def __init__(self, config: RiskConfig):
        self.config = config
    
    def calculate_stop_loss(
        self,
        entry_price: float,
        atr_n: float
    ) -> tuple[float, str]:
        """
        손절가 계산 (2N vs 8% 중 타이트한 것)
        
        Returns:
            (손절가, 적용 기준)
        """
        stop_2n = entry_price - (self.config.stop_loss_atr_multiplier * atr_n)
        stop_8pct = entry_price * (1 - self.config.stop_loss_max_percent)
        
        if stop_2n >= stop_8pct:
            return (stop_2n, "2N")
        return (stop_8pct, "8%")
    
    def calculate_position_size(
        self,
        account_value: float,
        entry_price: float,
        stop_loss_price: float
    ) -> int:
        """
        2% 룰 기반 포지션 크기 계산
        
        Returns:
            매수 수량
        """
        max_loss = account_value * self.config.risk_per_unit
        risk_per_share = entry_price - stop_loss_price
        
        if risk_per_share <= 0:
            raise ValueError("Invalid stop loss price")
        
        return int(max_loss / risk_per_share)


# src/risk/unit_limits.py

class UnitLimitManager:
    """Unit 한도 관리"""
    
    def __init__(self, config: RiskConfig, position_repo: PositionRepository):
        self.config = config
        self.position_repo = position_repo
    
    async def get_current_units(self) -> int:
        """현재 사용 중인 총 Unit 수"""
        pass
    
    async def get_available_units(self) -> int:
        """사용 가능한 Unit 수"""
        current = await self.get_current_units()
        return self.config.max_units_total - current
    
    async def can_add_unit(self, symbol: str) -> bool:
        """추가 Unit 가능 여부 확인"""
        available = await self.get_available_units()
        if available <= 0:
            return False
        
        stock_units = await self.get_stock_units(symbol)
        return stock_units < self.config.max_units_per_stock
    
    async def get_stock_units(self, symbol: str) -> int:
        """특정 종목의 현재 Unit 수"""
        pass
    
    async def get_sector_units(self, sector: str) -> int:
        """특정 섹터의 현재 Unit 수"""
        pass
```

#### 6.2.4 Order Execution

```python
# src/execution/broker_interface.py

from abc import ABC, abstractmethod
from decimal import Decimal
from dataclasses import dataclass

@dataclass
class AccountBalance:
    total_value: Decimal
    cash_balance: Decimal
    securities_value: Decimal
    buying_power: Decimal

@dataclass
class OrderResponse:
    success: bool
    order_id: str | None
    message: str

class BrokerInterface(ABC):
    """브로커 인터페이스 (모의/실제 공통, 비동기)"""
    
    @abstractmethod
    async def connect(self) -> bool: ...
    
    @abstractmethod
    async def disconnect(self) -> None: ...
    
    @abstractmethod
    async def get_balance(self) -> AccountBalance: ...
    
    @abstractmethod
    async def get_positions(self) -> list[dict]: ...
    
    @abstractmethod
    async def place_order(self, request: "OrderRequest") -> OrderResponse: ...
    
    @abstractmethod
    async def get_current_price(self, symbol: str) -> Decimal: ...
    
    @property
    @abstractmethod
    def is_paper_trading(self) -> bool: ...


class PaperBroker(BrokerInterface):
    """모의투자 브로커 (인메모리 시뮬레이션, 한투 API 미사용)"""
    
    def __init__(self, initial_cash: Decimal = Decimal("100000000")):
        self._cash = initial_cash
        self._positions: dict[str, "BrokerPosition"] = {}
        self._orders: dict[str, "BrokerOrder"] = {}


class LiveBroker(BrokerInterface):
    """실제투자 브로커 (한투 KIS API 연동)"""
    pass


# src/execution/order_manager.py

class OrderManager:
    """주문 관리자"""
    
    def __init__(
        self,
        broker: BrokerInterface,
        position_sizer: PositionSizer,
        unit_manager: UnitLimitManager,
        config: Settings
    ):
        self.broker = broker
        self.position_sizer = position_sizer
        self.unit_manager = unit_manager
        self.config = config
    
    async def execute_entry(self, signal: SignalDTO) -> Optional[Order]:
        """
        진입 주문 실행
        
        1. Unit 한도 확인
        2. 포지션 크기 계산
        3. 주문 실행
        4. 포지션 기록
        """
        pass
    
    async def execute_exit(self, signal: SignalDTO) -> Optional[Order]:
        """청산 주문 실행"""
        pass
    
    async def execute_pyramid(self, signal: SignalDTO) -> Optional[Order]:
        """피라미딩 주문 실행"""
        pass
```

---

## 7. API 연동 명세

### 7.1 한국투자증권 Open API

```python
# src/data/kis_client.py

from python_kis import KoreaInvestment

class KISClient:
    """한국투자증권 API 클라이언트 래퍼"""
    
    def __init__(self, config: Settings):
        self.config = config
        self._client = None
    
    @property
    def client(self) -> KoreaInvestment:
        if self._client is None:
            if self.config.trading_mode == TradingMode.PAPER:
                self._client = KoreaInvestment(
                    api_key=self.config.kis_paper_app_key,
                    api_secret=self.config.kis_paper_app_secret,
                    acc_no=self.config.kis_paper_account,
                    mock=True  # 모의투자
                )
            else:
                self._client = KoreaInvestment(
                    api_key=self.config.kis_live_app_key,
                    api_secret=self.config.kis_live_app_secret,
                    acc_no=self.config.kis_live_account,
                    mock=False  # 실거래
                )
        return self._client
    
    # === 시세 조회 ===
    
    async def get_current_price(self, symbol: str) -> dict:
        """현재가 조회"""
        pass
    
    async def get_daily_prices(
        self, 
        symbol: str, 
        period: int = 100
    ) -> list[PriceDTO]:
        """일봉 데이터 조회"""
        pass
    
    # === 주문 ===
    
    async def buy_market(self, symbol: str, quantity: int) -> dict:
        """시장가 매수"""
        pass
    
    async def sell_market(self, symbol: str, quantity: int) -> dict:
        """시장가 매도"""
        pass
    
    # === 계좌 ===
    
    async def get_balance(self) -> dict:
        """예수금 조회"""
        pass
    
    async def get_positions(self) -> list[dict]:
        """보유 종목 조회"""
        pass
```

### 7.2 DART OpenAPI

```python
# src/data/dart_client.py

import httpx

class DARTClient:
    """DART OpenAPI 클라이언트"""
    
    BASE_URL = "https://opendart.fss.or.kr/api"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient()
    
    async def get_financial_statements(
        self,
        corp_code: str,
        year: int,
        report_code: str = "11011"  # 사업보고서
    ) -> dict:
        """재무제표 조회"""
        pass
    
    async def get_company_info(self, corp_code: str) -> dict:
        """기업 기본 정보 조회"""
        pass
    
    async def search_company(self, name: str) -> list[dict]:
        """기업 검색"""
        pass
```

---

## 8. 테스트 요구사항

### 8.1 단위 테스트

```python
# tests/unit/test_canslim.py

import pytest
from src.screener.criteria.c_earnings import CEarnings

class TestCEarnings:
    """C 지표 (분기 실적) 테스트"""
    
    def test_eps_growth_pass(self):
        """EPS 20% 이상 성장 시 통과"""
        result = CEarnings.check(
            current_eps=1200,
            year_ago_eps=1000,  # 20% 성장
            current_revenue=100_000_000,
            year_ago_revenue=80_000_000  # 25% 성장
        )
        assert result['c_passed'] is True
    
    def test_eps_growth_fail(self):
        """EPS 20% 미만 성장 시 실패"""
        result = CEarnings.check(
            current_eps=1100,
            year_ago_eps=1000,  # 10% 성장
            current_revenue=130_000_000,
            year_ago_revenue=100_000_000
        )
        assert result['c_passed'] is False
    
     def test_revenue_growth_fail(self):
         """EPS 30% 성장 시 통과 (매출은 보조 지표, 통과에 무관)"""
         result = CEarnings.check(
             current_eps=1300,
             year_ago_eps=1000,  # 30% 성장
             current_revenue=110_000_000,
             year_ago_revenue=100_000_000  # 10% 성장
         )
         assert result['c_passed'] is True


# tests/unit/test_position_sizing.py

class TestPositionSizing:
    """포지션 사이징 테스트"""
    
    def test_stop_loss_2n_tighter(self):
        """2N이 더 타이트한 경우"""
        sizer = PositionSizer(RiskConfig())
        stop, reason = sizer.calculate_stop_loss(
            entry_price=50000,
            atr_n=1500  # 2N = 3000, 8% = 4000
        )
        assert stop == 47000
        assert reason == "2N"
    
    def test_stop_loss_8pct_tighter(self):
        """8%가 더 타이트한 경우"""
        sizer = PositionSizer(RiskConfig())
        stop, reason = sizer.calculate_stop_loss(
            entry_price=50000,
            atr_n=3000  # 2N = 6000, 8% = 4000
        )
        assert stop == 46000
        assert reason == "8%"
    
    def test_position_size_calculation(self):
        """포지션 크기 계산"""
        sizer = PositionSizer(RiskConfig())
        size = sizer.calculate_position_size(
            account_value=100_000_000,
            entry_price=50000,
            stop_loss_price=46000
        )
        # 2% of 1억 = 200만, 리스크 4000원/주 = 500주
        assert size == 500
```

### 8.2 통합 테스트

```python
# tests/integration/test_full_flow.py

import pytest
from src.screener.canslim import CANSLIMScreener
from src.signals.turtle import TurtleSignalEngine
from src.execution.order_manager import OrderManager

@pytest.mark.integration
class TestFullTradingFlow:
    """전체 트레이딩 플로우 통합 테스트"""
    
    async def test_screening_to_signal(self):
        """스크리닝 → 시그널 생성"""
        pass
    
    async def test_signal_to_order(self):
        """시그널 → 주문 실행"""
        pass
    
    async def test_paper_trading_cycle(self):
        """모의투자 전체 사이클"""
        pass
```

### 8.3 백테스트

```python
# tests/backtest/test_strategy.py

class TestBacktest:
    """백테스트"""
    
    def test_canslim_turtle_strategy(self):
        """CANSLIM + Turtle 전략 백테스트"""
        pass
    
    def test_drawdown_within_limit(self):
        """최대 드로우다운 40% 이내 확인"""
        pass
```

---

## 9. 배포 요구사항

### 9.1 로컬 개발 환경

```bash
# 1. 저장소 클론
git clone https://github.com/xxx/turtle-canslim.git
cd turtle-canslim

# 2. 가상환경 생성
python -m venv .venv
source .venv/bin/activate

# 3. 의존성 설치
pip install -e ".[dev]"

# 4. 환경변수 설정
cp .env.example .env
# .env 파일 편집

# 5. DB 마이그레이션
alembic upgrade head

# 6. 테스트 실행
pytest
```

### 9.2 프로덕션 환경

| 항목 | 권장 사양 |
|------|----------|
| 서버 | 클라우드 VM (AWS EC2, GCP, etc.) |
| OS | Ubuntu 22.04 LTS |
| CPU | 2+ cores |
| RAM | 8GB+ |
| 디스크 | 50GB+ SSD |
| 네트워크 | 고정 IP 권장 |

### 9.3 모니터링

| 도구 | 용도 |
|------|------|
| structlog | 구조화된 로깅 |
| Sentry | 에러 트래킹 |
| Prometheus + Grafana | 메트릭 모니터링 (선택) |

---

## 체크리스트

### MVP (Phase 1)

- [ ] 프로젝트 구조 생성
- [ ] 설정 관리 구현
- [ ] 한투 API 연동
- [ ] DART API 연동
- [ ] DB 스키마 생성
- [ ] CANSLIM C, A, L 지표 구현
- [ ] CLI 스크리너 구현

### Phase 2

- [ ] Turtle 진입/청산 로직
- [ ] ATR 계산
- [ ] 백테스트 프레임워크

### Phase 3

- [ ] 리스크 관리 (2% 룰, Unit 한도)
- [ ] 포지션 사이징

### Phase 4

- [ ] 주문 실행 (모의투자)
- [ ] 포트폴리오 관리

### Phase 5

- [ ] 해외 주식 지원

### Phase 6

- [ ] Telegram 알림
- [ ] 모니터링
- [ ] 프로덕션 배포
