# Turtle-CANSLIM 설정 가이드

> **최종 업데이트**: 2026-01-20  
> **요구 시간**: 약 30분  
> **지원 시장**: 국내 (KRX), 해외 (NYSE, NASDAQ)

---

## 목차

1. [사전 요구사항](#1-사전-요구사항)
2. [API 키 발급](#2-api-키-발급)
3. [데이터베이스 설정](#3-데이터베이스-설정)
4. [프로젝트 설치](#4-프로젝트-설치)
5. [환경변수 설정](#5-환경변수-설정)
6. [실행 방법](#6-실행-방법)
7. [모의투자 → 실거래 전환](#7-모의투자--실거래-전환)
8. [문제 해결](#8-문제-해결)
9. [주의사항 및 면책조항](#9-주의사항-및-면책조항)

---

## 1. 사전 요구사항

### 시스템 요구사항

| 항목 | 요구사항 |
|------|----------|
| OS | macOS, Linux (Windows WSL2 가능) |
| Python | 3.11 이상 |
| 메모리 | 최소 4GB RAM |
| 디스크 | 최소 10GB |
| 네트워크 | 안정적인 인터넷 연결 |

### 필요한 계정

| 서비스 | 용도 | 필수 여부 |
|--------|------|----------|
| 한국투자증권 | 국내/해외 시세, 주문 | **필수** |
| DART OpenAPI | 국내 재무제표 | 국내 투자 시 필수 |
| SEC EDGAR | 미국 재무제표 | 해외 투자 시 필수 (무료, API 키 불필요) |
| Telegram | 알림 수신 | 선택 |

---

## 2. API 키 발급

### 2.1 한국투자증권 Open API

#### Step 1: 계좌 개설
1. [한국투자증권](https://www.truefriend.com/) 홈페이지에서 비대면 계좌 개설
2. 주식 매매가 가능한 종합계좌 필요

#### Step 2: Open API 신청
1. [한국투자증권 Open API 포털](https://apiportal.koreainvestment.com/) 접속
2. 회원가입 및 로그인
3. **[마이페이지] → [API 신청]** 클릭
4. 서비스 약관 동의 후 신청

#### Step 3: 앱 키 발급
1. **[마이페이지] → [앱 관리]** 클릭
2. **[앱 추가]** 버튼 클릭
3. 앱 이름 입력 (예: "turtle-canslim")
4. 생성된 **App Key**와 **App Secret** 복사 및 보관

#### Step 4: 모의투자 계좌 설정
1. **[마이페이지] → [모의투자]** 접속
2. 모의투자 신청 (자동 승인)
3. 모의투자 계좌번호 확인 (예: 50012345-01)

> **중요**: 모의투자와 실거래용 앱 키가 별도입니다.
> - 모의투자용: App Key가 `PS`로 시작
> - 실거래용: App Key가 `PS`로 시작하지 않음

---

### 2.2 DART OpenAPI

#### Step 1: 회원가입
1. [DART OpenAPI](https://opendart.fss.or.kr/) 접속
2. **[인증키 신청]** 클릭
3. 회원가입 진행

#### Step 2: API 키 발급
1. 로그인 후 **[인증키 신청]** 클릭
2. 이용약관 동의
3. 인증키 발급 (즉시 발급)
4. 발급된 API Key 복사 및 보관

> **일일 요청 한도**: 10,000건/일  
> **주의**: 키를 분실하면 재발급 필요

---

### 2.3 Telegram Bot (선택)

#### Step 1: Bot 생성
1. Telegram에서 [@BotFather](https://t.me/BotFather) 검색
2. `/newbot` 명령어 입력
3. Bot 이름 입력 (예: "My Turtle Trading Bot")
4. Bot 사용자명 입력 (예: "my_turtle_bot")
5. 생성된 **Bot Token** 복사 및 보관

#### Step 2: Chat ID 확인
1. 생성한 Bot과 대화 시작 (`/start` 입력)
2. 브라우저에서 아래 URL 접속:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
3. JSON 응답에서 `chat.id` 값 확인 (예: 123456789)

> **Tip**: 그룹에서 사용하려면 Bot을 그룹에 추가한 후 동일하게 Chat ID 확인

---

### 2.4 SEC EDGAR (미국 재무제표)

SEC EDGAR는 미국 증권거래위원회(SEC)에서 제공하는 **무료 공개 API**입니다.

#### 특징
- **API 키 불필요**: 공개 데이터로 인증 없이 사용 가능
- **User-Agent 필수**: SEC 정책상 요청 시 User-Agent 헤더 필수
- **Rate Limit**: 10 requests/second (초당 10건)
- **데이터**: 10-K (연간), 10-Q (분기) 재무제표

#### 설정 방법
별도의 가입이나 키 발급이 필요 없습니다. `.env` 파일에 User-Agent만 설정하면 됩니다:

```bash
# 형식: "앱이름 연락처이메일"
SEC_USER_AGENT=TurtleCANSLIM contact@example.com
```

> **중요**: SEC는 User-Agent가 없거나 부적절한 요청을 차단합니다.  
> 반드시 유효한 이메일 주소를 포함하세요.

#### 제공 데이터
| 항목 | US-GAAP 태그 |
|------|-------------|
| 매출 | `us-gaap:Revenues` |
| 순이익 | `us-gaap:NetIncomeLoss` |
| EPS | `us-gaap:EarningsPerShareBasic` |
| 총자산 | `us-gaap:Assets` |
| 자기자본 | `us-gaap:StockholdersEquity` |

---

## 3. 데이터베이스 설정

### 3.1 PostgreSQL 설치

#### macOS (Homebrew)
```bash
# PostgreSQL 설치
brew install postgresql@15

# 서비스 시작
brew services start postgresql@15

# 버전 확인
psql --version
```

#### Ubuntu/Debian
```bash
# PostgreSQL 설치
sudo apt update
sudo apt install postgresql postgresql-contrib

# 서비스 시작
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

#### Docker (권장)
```bash
# PostgreSQL 컨테이너 실행
docker run -d \
  --name turtle-postgres \
  -e POSTGRES_USER=turtle \
  -e POSTGRES_PASSWORD=your_secure_password \
  -e POSTGRES_DB=turtle_canslim \
  -p 5432:5432 \
  -v turtle_pgdata:/var/lib/postgresql/data \
  postgres:15
```

### 3.2 데이터베이스 생성

```bash
# PostgreSQL 접속 (로컬 설치 시)
sudo -u postgres psql

# 사용자 생성
CREATE USER turtle WITH PASSWORD 'your_secure_password';

# 데이터베이스 생성
CREATE DATABASE turtle_canslim OWNER turtle;

# 권한 부여
GRANT ALL PRIVILEGES ON DATABASE turtle_canslim TO turtle;

# 종료
\q
```

### 3.3 연결 테스트

```bash
# 연결 테스트
psql -h localhost -U turtle -d turtle_canslim

# 성공 시 프롬프트: turtle_canslim=>
```

---

## 4. 프로젝트 설치

### 4.1 저장소 클론

```bash
# 저장소 클론
git clone https://github.com/xxx/turtle-canslim.git
cd turtle-canslim
```

### 4.2 가상환경 설정

```bash
# Python 버전 확인
python3 --version  # 3.11 이상 필요

# 가상환경 생성
python3 -m venv .venv

# 가상환경 활성화
source .venv/bin/activate  # macOS/Linux
# Windows: .venv\Scripts\activate
```

### 4.3 의존성 설치

```bash
# 개발 의존성 포함 설치
pip install -e ".[dev]"

# 설치 확인
pip list | grep turtle-canslim
```

### 4.4 DB 마이그레이션

```bash
# 마이그레이션 실행
alembic upgrade head

# 마이그레이션 상태 확인
alembic current
```

---

## 5. 환경변수 설정

### 5.1 .env 파일 생성

```bash
# 템플릿 복사
cp .env.example .env

# 편집기로 열기
nano .env  # 또는 vim, code 등
```

### 5.2 필수 설정값

```bash
# .env 파일 내용

# ===== 트레이딩 모드 =====
# paper: 모의투자 (기본값, 권장)
# live: 실거래 (주의 필요!)
TRADING_MODE=paper

# ===== 한국투자증권 API (모의투자) =====
KIS_PAPER_APP_KEY=PSxxxxxxxxxxxxxxxxxxxxxxxx
KIS_PAPER_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIS_PAPER_ACCOUNT=50012345-01

# ===== 한국투자증권 API (실거래) =====
# 경고: 실거래 전환 전까지 비워두세요!
KIS_LIVE_APP_KEY=
KIS_LIVE_APP_SECRET=
KIS_LIVE_ACCOUNT=

# ===== DART OpenAPI (국내 재무제표) =====
DART_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ===== SEC EDGAR (미국 재무제표) =====
# API 키 불필요, User-Agent만 설정
SEC_USER_AGENT=TurtleCANSLIM contact@example.com

# ===== 데이터베이스 =====
DATABASE_URL=postgresql://turtle:your_secure_password@localhost:5432/turtle_canslim

# ===== Redis (선택) =====
REDIS_URL=redis://localhost:6379/0

# ===== Telegram (선택) =====
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

### 5.3 설정값 설명

| 변수 | 설명 | 예시 |
|------|------|------|
| `TRADING_MODE` | `paper` (모의) 또는 `live` (실거래) | `paper` |
| `KIS_PAPER_APP_KEY` | 모의투자 앱 키 (`PS`로 시작) | `PSxxxxxxxx` |
| `KIS_PAPER_APP_SECRET` | 모의투자 앱 시크릿 | 40자 문자열 |
| `KIS_PAPER_ACCOUNT` | 모의투자 계좌번호 | `50012345-01` |
| `DART_API_KEY` | DART API 키 (국내) | 40자 문자열 |
| `SEC_USER_AGENT` | SEC 요청 식별자 (해외) | `AppName email@example.com` |
| `DATABASE_URL` | PostgreSQL 연결 문자열 | `postgresql://user:pass@host:port/db` |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot 토큰 | `123456789:ABC...` |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | `123456789` |

---

## 6. 실행 방법

### 6.1 TUI (Terminal User Interface) 실행

대화형 터미널 인터페이스로 시스템을 모니터링하고 제어할 수 있습니다.

```bash
# TUI 실행 (권장)
python scripts/run_tui.py

# 또는 설치된 명령어 사용
turtle-tui
```

#### TUI 화면 구성

| 탭 | 내용 |
|-----|------|
| **Portfolio** | 보유 포지션 테이블 (종목, 수량, 진입가, 현재가, 손익, Units, 손절가) |
| **Candidates** | CANSLIM 후보 종목 (점수, 각 지표 통과 여부, RS Rating, EPS 성장률) |
| **Signals** | 트레이딩 시그널 히스토리 (시간, 종목, 유형, 시스템, 가격, ATR, 상태) |
| **Settings** | 현재 설정값 확인 (CANSLIM, Turtle, Risk 파라미터, API 상태) |

#### 키보드 단축키

| 키 | 기능 |
|----|------|
| `R` | 데이터 새로고침 |
| `S` | CANSLIM 스크리닝 실행 |
| `T` | 트레이딩 사이클 실행 |
| `D` | 다크/라이트 모드 전환 |
| `1-4` | 탭 전환 (1: Portfolio, 2: Candidates, 3: Signals, 4: Settings) |
| `Q` | 종료 |

#### SSH 원격 접속

Vultr 등 원격 서버에서 SSH로 접속 후 바로 TUI 사용 가능:

```bash
# 서버 접속
ssh user@your-server.com

# 가상환경 활성화 후 TUI 실행
cd turtle-canslim
source .venv/bin/activate
turtle-tui
```

> **Tip**: tmux 또는 screen과 함께 사용하면 세션 유지 가능
> ```bash
> tmux new -s turtle
> turtle-tui
> # Ctrl+B, D로 detach
> # tmux attach -t turtle로 재접속
> ```

---

### 6.2 스크리닝 실행 (CLI)

CANSLIM 기준으로 종목을 스크리닝합니다.

```bash
# 기본 실행 (국내 시장 - DART API 사용)
python scripts/run_screener.py

# 미국 시장 스크리닝 (SEC EDGAR API 사용)
python scripts/run_screener.py --market us

# 특정 미국 종목만 스크리닝
python scripts/run_screener.py --market us --symbols AAPL,MSFT,GOOGL,AMZN,META

# 결과 저장
python scripts/run_screener.py --output results/screening_$(date +%Y%m%d).csv
```

**국내 시장 출력 예시**:
```
=== CANSLIM 스크리닝 결과 (KRX) ===
데이터 소스: DART OpenAPI
총 후보 종목: 15개

종목코드   종목명        C    A    N    S    L    I    M    점수
005930    삼성전자      ✓    ✓    ✓    ✓    ✓    ✓    ✓    7/7
035420    NAVER        ✓    ✓    ✓    ✗    ✓    ✓    ✓    6/7
...
```

**미국 시장 출력 예시**:
```
=== CANSLIM 스크리닝 결과 (US) ===
데이터 소스: SEC EDGAR
총 후보 종목: 8개

종목코드   종목명        C    A    N    S    L    I    M    점수
AAPL      Apple Inc    ✓    ✓    ✓    ✓    ✓    ✓    ✓    7/7
NVDA      NVIDIA       ✓    ✓    ✓    ✓    ✓    ✗    ✓    6/7
...
```

> **참고**: 미국 시장 스크리닝은 SEC EDGAR API Rate Limit (10 req/s)으로 인해  
> 종목 수에 따라 시간이 걸릴 수 있습니다. 배치 업데이트 권장.

### 6.3 트레이딩 실행

자동 매매를 실행합니다.

```bash
# 모의투자 모드 (기본)
python scripts/run_trading.py --mode paper

# 실거래 모드 (주의!)
python scripts/run_trading.py --mode live

# 백그라운드 실행
nohup python scripts/run_trading.py --mode paper > logs/trading.log 2>&1 &
```

**트레이딩 프로세스**:
1. 장 시작 전: CANSLIM 스크리닝
2. 장 중: Turtle 시그널 모니터링
3. 시그널 발생 시: 포지션 사이징 → 주문 실행
4. 장 마감 후: 일일 리포트 생성

### 6.4 백테스트 실행

과거 데이터로 전략을 검증합니다.

```bash
# 기본 백테스트 (최근 2년)
python scripts/run_backtest.py

# 기간 지정
python scripts/run_backtest.py --start 2023-01-01 --end 2024-12-31

# 초기 자본 지정
python scripts/run_backtest.py --capital 100000000
```

**백테스트 결과 예시**:
```
=== 백테스트 결과 ===
기간: 2023-01-01 ~ 2024-12-31
초기 자본: 100,000,000원

총 수익률: +45.2%
연환산 수익률: +22.6%
최대 드로우다운: -18.3%
샤프 비율: 1.42
승률: 58.7%
평균 보유 기간: 32일
```

---

## 7. 모의투자 → 실거래 전환

### 7.1 전환 전 체크리스트

- [ ] 모의투자에서 최소 3개월 이상 테스트 완료
- [ ] 백테스트 결과 확인 및 분석
- [ ] 리스크 관리 파라미터 검증
- [ ] 실거래용 API 키 발급 완료
- [ ] 투자 가능 금액 확보
- [ ] 손실 감내 범위 결정

### 7.2 실거래 설정

```bash
# .env 파일 수정
TRADING_MODE=live

# 실거래 API 키 설정
KIS_LIVE_APP_KEY=your_live_app_key
KIS_LIVE_APP_SECRET=your_live_app_secret
KIS_LIVE_ACCOUNT=12345678-01
```

### 7.3 실거래 주의사항

1. **소액으로 시작**: 처음에는 전체 자산의 10% 이하로 시작
2. **모니터링 필수**: 첫 1-2주는 실시간 모니터링 권장
3. **손절 확인**: 손절 주문이 정상 작동하는지 확인
4. **네트워크 안정성**: 안정적인 인터넷 환경 확보
5. **비상 연락처**: 한투 고객센터 번호 저장 (1544-5000)

### 7.4 긴급 중지 방법

```bash
# 트레이딩 프로세스 중지
pkill -f "run_trading.py"

# 또는 Ctrl+C (포그라운드 실행 시)

# 모든 미체결 주문 취소 (수동)
# 한국투자증권 MTS/HTS에서 직접 취소
```

---

## 8. 문제 해결

### 8.1 일반적인 오류

#### API 인증 실패
```
Error: Authentication failed
```
**해결**:
- App Key와 App Secret이 올바른지 확인
- 모의투자/실거래 키를 혼용하지 않았는지 확인
- 계좌번호가 올바른지 확인

#### 데이터베이스 연결 실패
```
Error: Connection refused
```
**해결**:
- PostgreSQL 서비스 실행 여부 확인: `sudo systemctl status postgresql`
- DATABASE_URL 형식 확인
- 방화벽 설정 확인

#### DART API 한도 초과
```
Error: Rate limit exceeded
```
**해결**:
- 일일 10,000건 한도 확인
- 다음 날 자정(KST) 이후 재시도
- 요청 간격 조절

#### SEC EDGAR 접근 거부
```
Error: 403 Forbidden
```
**해결**:
- `SEC_USER_AGENT` 설정 확인 (형식: `앱이름 이메일`)
- 유효한 이메일 주소 사용
- Rate Limit 확인 (10 req/s 초과 금지)

#### SEC EDGAR 티커 미발견
```
Error: Ticker not found: XXXX
```
**해결**:
- 정확한 티커 심볼 확인 (대문자)
- ADR이 아닌 본주인지 확인
- SEC에 등록된 미국 기업인지 확인

### 8.2 로그 확인

```bash
# 로그 파일 위치
ls -la logs/

# 최근 로그 확인
tail -f logs/trading.log

# 에러만 필터링
grep "ERROR" logs/trading.log
```

### 8.3 지원 요청

문제 해결이 안 될 경우:
1. GitHub Issues에 문의
2. 로그 파일 첨부 (민감 정보 제거)
3. 재현 단계 설명

---

## 9. 주의사항 및 면책조항

### 9.1 투자 위험 고지

> **경고**: 이 시스템은 투자 참고용으로만 사용하세요.

- 주식 투자는 원금 손실 위험이 있습니다.
- 과거 수익률이 미래 수익을 보장하지 않습니다.
- 자동매매 시스템은 기술적 오류가 발생할 수 있습니다.
- 모든 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.

### 9.2 면책조항

본 소프트웨어 사용으로 인해 발생하는 어떠한 직접적, 간접적, 우발적, 특수적, 징벌적 또는 결과적 손해에 대해서도 개발자는 책임지지 않습니다.

여기에는 다음이 포함되나 이에 국한되지 않습니다:
- 투자 손실
- 시스템 오류로 인한 손해
- 데이터 손실
- 영업 중단

### 9.3 권장 사항

1. **충분한 테스트**: 실거래 전 최소 3개월 모의투자
2. **분산 투자**: 전체 자산의 일부만 시스템 매매에 사용
3. **손실 한도 설정**: 감내 가능한 최대 손실 금액 사전 설정
4. **정기 점검**: 주 1회 이상 시스템 상태 확인
5. **비상 계획**: 시스템 장애 시 대응 방안 마련

---

## 부록: 빠른 시작 요약

### 국내 주식 (KRX)
```bash
# 1. 저장소 클론 및 설치
git clone https://github.com/xxx/turtle-canslim.git
cd turtle-canslim
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. 환경 설정
cp .env.example .env
# .env 편집: KIS_*, DART_API_KEY, DATABASE_URL 설정

# 3. DB 마이그레이션
alembic upgrade head

# 4. 스크리닝 실행
python scripts/run_screener.py

# 5. 모의투자 실행
python scripts/run_trading.py --mode paper
```

### 미국 주식 (NYSE/NASDAQ)
```bash
# 1~3 단계는 동일

# 4. .env에 SEC User-Agent 추가
echo 'SEC_USER_AGENT=TurtleCANSLIM your@email.com' >> .env

# 5. 미국 시장 스크리닝
python scripts/run_screener.py --market us

# 6. 특정 종목만 스크리닝
python scripts/run_screener.py --market us --symbols AAPL,MSFT,GOOGL
```

### 데이터 소스 요약

| 시장 | 재무제표 소스 | 시세 소스 | 필요 설정 |
|------|-------------|----------|----------|
| KRX | DART OpenAPI | 한투 API | `DART_API_KEY` |
| US | SEC EDGAR | 한투 해외 API | `SEC_USER_AGENT` |

---

## 10. Docker로 실행하기

Docker를 사용하면 환경 설정 없이 바로 실행할 수 있습니다.

### 10.1 빠른 시작

```bash
# 1. .env 파일 설정
cp .env.example .env
nano .env  # API 키 입력

# 2. 빌드 및 실행
docker compose build
docker compose up -d postgres redis
docker compose run --rm migrate
docker compose up -d

# 3. 확인
docker compose ps
docker compose logs -f app
```

### 10.2 개별 서비스 실행

```bash
# 스크리닝
docker compose run --rm screener

# TUI
docker compose run --rm --profile tui tui

# 미국 시장 스크리닝
docker compose run --rm screener python scripts/run_screener.py --market us
```

### 10.3 서비스 관리

```bash
# 중지
docker compose down

# 재시작
docker compose restart

# 로그 확인
docker compose logs -f app
```

자세한 배포 방법은 [DEPLOY.md](./DEPLOY.md)를 참조하세요.

---

> **문서 버전**: 1.3.0 (Docker 지원 추가)  
> **관련 문서**: [SPEC.md](./SPEC.md), [DESIGN.md](./DESIGN.md), [TASKS.md](./TASKS.md), [DEPLOY.md](./DEPLOY.md)
