# Turtle-CANSLIM

CANSLIM 펀더멘탈 분석과 Turtle Trading 기술적 분석을 결합한 국내/해외 주식 자동매매 시스템

## 개요

- **CANSLIM**: William O'Neil의 방법론으로 우량 성장주 필터링
- **Turtle Trading**: 돌파 기반 진입/청산 시그널
- **리스크 관리**: 2% 룰 + Unit 한도 기반 포지션 관리

## 지원 시장

| 시장 | 거래소 | 상태 |
|------|--------|------|
| 국내 | KRX (KOSPI, KOSDAQ) | Phase 1 |
| 해외 | NYSE, NASDAQ | Phase 2 |

## 요구사항

- Python 3.11+
- PostgreSQL
- 한국투자증권 Open API 계정
- DART OpenAPI 키

## 설치

```bash
# 1. 저장소 클론
git clone https://github.com/xxx/turtle-canslim.git
cd turtle-canslim

# 2. 가상환경 생성
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 의존성 설치
pip install -e ".[dev]"

# 4. 환경변수 설정
cp .env.example .env
# .env 파일 편집

# 5. DB 마이그레이션
alembic upgrade head
```

## 사용법

### TUI (Terminal User Interface) - 권장

```bash
# TUI 실행
python scripts/run_tui.py
# 또는
turtle-tui
```

**TUI 단축키**: `R` 새로고침 | `S` 스크리닝 | `T` 트레이딩 | `D` 다크모드 | `Q` 종료

### CLI 명령어

```bash
# 스크리닝 실행
python scripts/run_screener.py

# 트레이딩 실행 (모의투자)
TRADING_MODE=paper python scripts/run_trading.py

# 백테스트 실행
python scripts/run_backtest.py
```

## 프로젝트 구조

```
turtle-canslim/
├── src/
│   ├── tui/            # TUI (Terminal User Interface)
│   ├── data/           # 데이터 계층 (API 클라이언트, DB)
│   ├── screener/       # CANSLIM 스크리너
│   ├── signals/        # Turtle Trading 시그널
│   ├── risk/           # 리스크 관리
│   ├── execution/      # 주문 실행
│   ├── notification/   # 알림 (Telegram)
│   └── core/           # 공통 (설정, 로깅, 예외)
├── tests/              # 테스트
├── scripts/            # 실행 스크립트
├── config/             # 설정 파일
└── docs/               # 문서
```

## 핵심 설정값

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

# 리스크 관리
risk:
  risk_per_unit: 0.02         # 2% 룰
  max_units_per_stock: 4      # 종목당 최대 4 Units
  max_units_total: 20         # 포트폴리오 최대 20 Units
  stop_loss_atr_multiplier: 2 # 2N 손절
  stop_loss_max_percent: 0.08 # 8% 손절 (둘 중 타이트한 것)
```

## Docker로 실행

```bash
# 빌드 및 실행
docker compose build
docker compose up -d

# 로그 확인
docker compose logs -f app

# TUI 실행
docker compose run --rm --profile tui tui
```

자세한 배포 방법은 [배포 가이드](docs/DEPLOY.md)를 참조하세요.

## 문서

- [설정 가이드](docs/SETUP.md)
- [배포 가이드](docs/DEPLOY.md) - Vultr VPS + Docker
- [설계 문서](docs/DESIGN.md)
- [기술 명세서](docs/SPEC.md)
- [태스크 목록](docs/TASKS.md)

## 라이선스

Private - All rights reserved

## 주의사항

이 시스템은 투자 참고용으로만 사용하세요. 실제 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다. 본 시스템 사용으로 인한 투자 손실에 대해 개발자는 책임지지 않습니다.
