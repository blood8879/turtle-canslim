# Turtle-CANSLIM AWS 배포 가이드 (데몬 모드)

> **최종 업데이트**: 2026-02-06
> **대상**: AWS EC2 (Ubuntu 22.04 LTS)
> **방식**: Docker Compose 데몬 운영
> **비용**: 프리티어 무료 (12개월) / 이후 t3.small ~$15/월

---

## 목차

1. [개요](#1-개요)
2. [사전 준비 (EC2)](#2-사전-준비-ec2)
3. [서버 초기 설정](#3-서버-초기-설정)
4. [Docker 설치](#4-docker-설치)
5. [프로젝트 배포](#5-프로젝트-배포)
6. [최초 실행](#6-최초-실행)
7. [데몬 동작 확인](#7-데몬-동작-확인)
8. [운영 관리](#8-운영-관리)
9. [TUI 사용법](#9-tui-사용법)
10. [모니터링](#10-모니터링)
11. [문제 해결](#11-문제-해결)
12. [보안](#12-보안)
13. [프리티어 주의사항](#13-프리티어-주의사항)
14. [부록: 빠른 시작 요약](#부록-빠른-시작-요약)
15. [부록: 명령어 모음](#부록-명령어-모음)

---

## 1. 개요

### 1.1 시스템 구성

Turtle-CANSLIM은 CANSLIM 펀더멘탈 분석 + Turtle Trading 시그널을 결합한 자동매매 시스템입니다. AWS EC2에서 **Docker Compose 데몬**으로 24시간 무중단 운영됩니다.

### 1.2 서비스 아키텍처

```
docker compose up -d (상시 실행)
├── postgres   — PostgreSQL 15 데이터베이스
├── redis      — Redis 7 캐시
└── app        — 트레이딩 봇 데몬 (APScheduler 기반)

docker compose run --rm --profile migrate migrate    — DB 마이그레이션 (1회성)
docker compose run --rm --profile screener screener   — 수동 스크리닝 (1회성)
docker compose run --rm --profile tui tui             — TUI 인터페이스 (대화형)
```

### 1.3 데몬 생명주기

```
서버 부팅
  → Docker 자동시작 (systemctl enable docker)
  → 컨테이너 자동복구 (restart: unless-stopped)
    → APScheduler 기동
      → 데이터 수집 (장 시작 전)
      → CANSLIM 스크리닝 (장 시작 전)
      → 실시간 시그널 체크 (장중 N분 간격)
        → 돌파 근접 종목 감시 (3초 간격 fast poll)
      → 일일 리포트 (장 종료 후)
    → 다음 날 반복
```

### 1.4 스케줄 (APScheduler Cron)

| 시장 | 작업 | 시간 | 타임존 |
|------|------|------|--------|
| KRX | 데이터 수집 | 월-금 07:30 | KST |
| KRX | CANSLIM 스크리닝 | 월-금 08:00 | KST |
| KRX | 실시간 시그널 체크 | 월-금 09:00-15:00 (N분 간격) | KST |
| KRX | 일일 리포트 | 월-금 16:00 | KST |
| US | 데이터 수집 | 월-금 20:00 | KST |
| US | CANSLIM 스크리닝 | 월-금 21:00 | KST |
| US | 실시간 시그널 체크 | 월-금 09:00-15:00 (N분 간격) | EST |
| US | 일일 리포트 | 월-금 16:30 | EST |

봇은 SIGINT/SIGTERM을 수신하면 현재 사이클을 완료한 뒤 graceful shutdown합니다.

---

## 2. 사전 준비 (EC2)

### 2.1 서버 사양

| 항목 | 프리티어 (테스트) | 실사용 권장 |
|------|-----------------|------------|
| 인스턴스 | t2.micro | t3.small |
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GB | 2 GB |
| Storage | 30 GB EBS (gp2) | 40 GB EBS (gp3) |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Region | ap-northeast-2 (서울) | ap-northeast-2 (서울) |

> t2.micro (1GB RAM)에서는 **스왑 설정 필수**. Paper 트레이딩 테스트용으로 충분합니다.

### 2.2 EC2 인스턴스 생성

1. [AWS Console](https://console.aws.amazon.com/ec2/) 로그인
2. **Launch Instance** 클릭
3. 설정:
   - **Name**: `turtle-canslim`
   - **AMI**: Ubuntu Server 22.04 LTS (Free tier eligible)
   - **Instance type**: t2.micro (Free tier eligible)
   - **Key pair**: 새로 생성 또는 기존 키 선택 → `.pem` 파일 다운로드
   - **Network settings**: Security Group 생성 (아래 참조)
   - **Storage**: 30 GB gp2 (프리티어 한도)
4. **Launch Instance** 클릭

### 2.3 Security Group

| Type | Port | Source | 용도 |
|------|------|--------|------|
| SSH | 22 | My IP | SSH 접속 |

> PostgreSQL(5432), Redis(6379) 포트는 **열지 마세요**. Docker 내부 네트워크로만 통신합니다.

### 2.4 Elastic IP (권장)

인스턴스를 중지/시작하면 Public IP가 변경됩니다.

1. **EC2 > Elastic IPs > Allocate Elastic IP address**
2. 할당된 IP 선택 → **Associate Elastic IP address**
3. 인스턴스 선택 후 연결

> 실행 중인 인스턴스에 연결되어 있으면 **무료**. 미연결 시 과금됩니다.

### 2.5 SSH 접속

```bash
chmod 400 ~/Downloads/your-key.pem
ssh -i ~/Downloads/your-key.pem ubuntu@YOUR_ELASTIC_IP
```

---

## 3. 서버 초기 설정

### 3.1 시스템 업데이트

```bash
sudo apt update && sudo apt upgrade -y
```

### 3.2 타임존 설정

```bash
sudo timedatectl set-timezone Asia/Seoul
timedatectl
```

### 3.3 스왑 설정 (t2.micro 필수)

t2.micro는 RAM 1GB뿐이므로 **스왑 없이 실행하면 OOM으로 컨테이너가 죽습니다**.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

free -h
```

예상 출력:

```
              total        used        free
Mem:          981Mi       150Mi       600Mi
Swap:         2.0Gi         0B        2.0Gi
```

---

## 4. Docker 설치

### 4.1 Docker Engine 설치

```bash
sudo apt install -y ca-certificates curl gnupg lsb-release

sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
newgrp docker

docker --version
docker compose version
```

### 4.2 Docker 자동 시작

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

---

## 5. 프로젝트 배포

### 5.1 저장소 클론

```bash
mkdir -p ~/apps && cd ~/apps
git clone https://github.com/YOUR_USERNAME/turtle-canslim.git
cd turtle-canslim
```

### 5.2 환경변수 설정

```bash
cp .env.example .env
nano .env
```

`.env` 파일 내용:

```bash
# 트레이딩 모드
TRADING_MODE=paper

# 데이터베이스
POSTGRES_USER=turtle
POSTGRES_PASSWORD=YOUR_SECURE_PASSWORD_HERE
POSTGRES_DB=turtle_canslim

# 한국투자증권 API (모의투자)
KIS_PAPER_APP_KEY=PSxxxxxxxxxxxxxxxx
KIS_PAPER_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIS_PAPER_ACCOUNT=50012345-01

# DART API
DART_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# SEC EDGAR
SEC_USER_AGENT=TurtleCANSLIM your@email.com

# Telegram (선택)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

```bash
chmod 600 .env
```

### 5.3 디렉토리 생성

```bash
mkdir -p logs results
```

### 5.4 docker-compose.yml 커맨드 수정

기본 설정은 KRX만 트레이딩합니다. KRX + US 모두 운영하려면:

```bash
nano docker-compose.yml
```

`app` 서비스의 `command`를 다음과 같이 변경:

```yaml
command: ["python", "scripts/run_trading.py", "--market", "both"]
```

---

## 6. 최초 실행

### 6.1 Docker 이미지 빌드

```bash
docker compose build
```

> t2.micro에서 5-10분 소요됩니다. 빌드가 `Killed`로 실패하면 스왑 설정을 확인하세요.

### 6.2 인프라 서비스 시작

```bash
docker compose up -d postgres redis
```

PostgreSQL 헬스체크가 완료될 때까지 10-15초 대기합니다.

```bash
docker compose ps
```

`postgres`와 `redis`가 `healthy` 상태인지 확인합니다.

### 6.3 데이터베이스 마이그레이션

```bash
docker compose run --rm --profile migrate migrate
```

정상 출력:

```
INFO  [alembic.runtime.migration] Running upgrade  -> 001, initial schema
INFO  [alembic.runtime.migration] Running upgrade 001 -> 002, add stock canslim fields
INFO  [alembic.runtime.migration] Running upgrade 002 -> 003, add earnings tracking
```

### 6.4 데몬 시작

```bash
docker compose up -d
```

이 명령어 하나로 `app` 데몬이 시작됩니다. 터미널을 종료해도 계속 실행됩니다.

```bash
docker compose logs -f app
```

정상 시작 시 출력:

```
============================================================
Turtle-CANSLIM Trading Bot
============================================================
Mode:   PAPER
Broker: KIS 모의투자 API
Market: BOTH
============================================================

Trading bot is running. Press Ctrl+C to stop.
```

---

## 7. 데몬 동작 확인

### 7.1 서비스 상태 확인

```bash
docker compose ps
```

예상 출력:

```
NAME              COMMAND                  STATUS          PORTS
turtle-app        "python scripts/run…"    Up 2 minutes
turtle-postgres   "docker-entrypoint.…"    Up 3 minutes (healthy)
turtle-redis      "docker-entrypoint.…"    Up 3 minutes (healthy)
```

3개 서비스 모두 `Up` 상태여야 합니다.

### 7.2 스케줄러 로그 확인

```bash
docker compose logs -f app
```

봇이 정상 동작하면 스케줄에 따라 다음과 같은 로그가 출력됩니다:

```
# 장 시작 전 — 데이터 수집
07:30:00 INFO  running_data_update market=krx
07:31:15 INFO  data_update_complete market=krx

# 장 시작 전 — CANSLIM 스크리닝
08:00:00 INFO  running_screening market=krx
08:02:30 INFO  screening_complete candidates=5

# 장중 — 실시간 시그널 체크 (N분 간격)
09:00:00 INFO  signal_cycle_start
09:00:03 INFO  realtime_prices_fetched count=42
09:00:05 INFO  signal_cycle_complete exits=0 entries=1 pyramids=0

# 돌파 근접 감시 (fast poll)
09:00:05 INFO  fast_poll_start watched=2 symbols=["005930", "035720"]

# 장 종료 후 — 일일 리포트
16:00:00 INFO  generating_daily_report
```

장이 열리지 않는 주말/공휴일에는 스케줄러가 작업을 건너뜁니다.

### 7.3 자동 복구 확인

`restart: unless-stopped` 설정으로 다음 상황에서 자동 복구됩니다:

| 상황 | 동작 |
|------|------|
| 앱 크래시 | Docker가 즉시 컨테이너 재시작 |
| 서버 재부팅 | Docker 서비스 자동시작 → 컨테이너 자동복구 |
| OOM Kill | Docker가 컨테이너 재시작 (스왑 설정 권장) |
| `docker compose stop` | 수동 중지 — 자동 재시작 안 함 |

---

## 8. 운영 관리

### 8.1 코드 업데이트 배포

```bash
cd ~/apps/turtle-canslim
git pull origin main
docker compose up -d --build
```

`--build` 플래그가 이미지를 재빌드한 뒤 컨테이너를 교체합니다. PostgreSQL/Redis 데이터는 Docker 볼륨에 보존됩니다.

### 8.2 데몬 재시작

```bash
docker compose restart app
```

### 8.3 데몬 중지

```bash
docker compose stop app
```

봇이 SIGTERM을 수신하면 현재 사이클을 완료한 뒤 graceful shutdown합니다.

### 8.4 전체 스택 중지

```bash
docker compose down
```

> 데이터는 Docker 볼륨에 보존됩니다. `docker compose down -v`는 볼륨도 삭제하므로 **데이터가 사라집니다**.

### 8.5 긴급 중지

```bash
docker kill turtle-app
```

### 8.6 마이그레이션 (스키마 변경 시)

코드 업데이트 후 새 마이그레이션이 있으면:

```bash
docker compose run --rm --profile migrate migrate
```

### 8.7 수동 스크리닝

데몬의 스케줄을 기다리지 않고 즉시 스크리닝하려면:

```bash
docker compose run --rm --profile screener screener
```

---

## 9. TUI 사용법

데몬이 백그라운드에서 실행되는 동안 TUI로 상태를 확인할 수 있습니다.

### 9.1 TUI 실행

```bash
docker compose run --rm --profile tui tui
```

> TUI는 대화형 터미널이 필요합니다. SSH 세션에서 실행하세요.

### 9.2 화면 구성

```
┌─────────────────────────────────────────────────────────────┐
│ 터틀-캔슬림                           CANSLIM + 터틀 트레이딩 │
├─────────────────────────────────────────────────────────────┤
│ 모드: PAPER  포지션: 0  유닛: 0/20  후보종목: 5  최근스캔: --  │
├─────────────────────────────────────────────────────────────┤
│ [포트폴리오] [후보종목] [시그널] [설정] [단축키]               │
├─────────────────────────────────────────────────────────────┤
│                    (탭 내용 영역)                            │
├─────────────────────────────────────────────────────────────┤
│ [새로고침] [KRX스크리닝] [US스크리닝] [전체스크리닝]           │
│           [KRX트레이딩] [US트레이딩]                         │
├─────────────────────────────────────────────────────────────┤
│ 10:30:15 데이터 새로고침 완료                                │
│ 10:30:20 KRX CANSLIM 스크리닝 시작...                       │
└─────────────────────────────────────────────────────────────┘
```

### 9.3 키보드 단축키

| 키 | 기능 |
|----|------|
| **R** | DB에서 데이터 새로고침 |
| **S** | 전체 스크리닝 (KRX + US) |
| **K** | KRX 스크리닝 |
| **N** | US 스크리닝 |
| **T** | KRX 트레이딩 시작/중지 |
| **Y** | US 트레이딩 시작/중지 |
| **U** | 가격 데이터 갱신 |
| **D** | 다크/라이트 모드 전환 |
| **1-5** | 탭 전환 (포트폴리오/후보종목/시그널/설정/단축키) |
| **Q** | TUI 종료 |

### 9.4 탭 설명

| 탭 | 내용 |
|----|------|
| **포트폴리오** | 보유 포지션 (종목, 수량, 매입가, 현재가, 손익, 손절가) |
| **후보종목** | CANSLIM 스크리닝 결과 (점수, C/A/N/S/L/I/M, RS, EPS%, 매출%, ROE) |
| **시그널** | 최근 트레이딩 시그널 (진입/청산/피라미딩) |
| **설정** | 현재 설정값 (CANSLIM 기준, 터틀 설정, 리스크 관리) |
| **단축키** | 키보드 단축키 안내 |

### 9.5 TUI vs 데몬

| | 데몬 (`docker compose up -d`) | TUI |
|--|-------------------------------|-----|
| 역할 | 자동 매매 실행 | 상태 확인 및 수동 조작 |
| 실행 방식 | 백그라운드 상시 실행 | SSH 접속 시 필요할 때 실행 |
| 스크리닝 | APScheduler 스케줄 | 수동 (키보드) |
| 트레이딩 | 자동 (스케줄 기반) | 수동 시작/중지 가능 |
| 종료 시 | 서버 재부팅해도 유지 | SSH 종료 시 함께 종료 |

> 데몬이 이미 자동 매매를 실행하고 있으므로, TUI는 **상태 확인 및 수동 스크리닝** 용도로 사용하세요.

---

## 10. 모니터링

### 10.1 실시간 로그

```bash
docker compose logs -f app
docker compose logs --tail=100 app
```

### 10.2 로그 파일

```bash
tail -f ~/apps/turtle-canslim/logs/trading.log
```

`trading.log`는 구조화된 JSON 로그로, 시그널 발생/체결/리포트 등 트레이딩 이벤트를 기록합니다.

### 10.3 컨테이너 리소스 사용량

```bash
docker stats
```

t2.micro에서 예상 메모리 사용량:

| 서비스 | 메모리 |
|--------|--------|
| postgres | ~100-150 MB |
| redis | ~10-30 MB |
| app | ~150-300 MB |
| **합계** | ~300-500 MB + 스왑 |

### 10.4 데이터베이스 접속

```bash
docker compose exec postgres psql -U turtle -d turtle_canslim
```

유용한 쿼리:

```sql
-- 현재 CANSLIM 후보 종목
SELECT s.symbol, s.name, cs.total_score, cs.c_eps_growth, cs.c_revenue_growth
FROM canslim_scores cs JOIN stocks s ON cs.stock_id = s.id
WHERE cs.is_candidate = true
ORDER BY cs.total_score DESC;

-- 오늘 발생한 시그널
SELECT s.symbol, sig.signal_type, sig.price, sig.timestamp
FROM signals sig JOIN stocks s ON sig.stock_id = s.id
WHERE sig.timestamp >= CURRENT_DATE
ORDER BY sig.timestamp DESC;

-- 열린 포지션
SELECT s.symbol, p.quantity, p.entry_price, p.stop_loss_price, p.units
FROM positions p JOIN stocks s ON p.stock_id = s.id
WHERE p.status = 'OPEN';
```

---

## 11. 문제 해결

### 11.1 빌드 중 메모리 부족 (Killed)

```bash
free -h

docker compose down
docker compose build
```

스왑이 설정되어 있는지 확인하세요 (3장 참조).

### 11.2 마이그레이션 실패: ModuleNotFoundError

```
ModuleNotFoundError: No module named 'src.data'
```

Docker 이미지가 최신 코드를 반영하지 않아 발생합니다. 캐시를 무시하고 재빌드:

```bash
docker compose build --no-cache
docker compose run --rm --profile migrate migrate
```

### 11.3 컨테이너 OOM Kill

```bash
docker inspect turtle-app | grep -i oom
docker stats --no-stream
```

스왑이 충분한지 확인하고, 부족하면 인스턴스를 t3.small로 업그레이드하세요.

### 11.4 데이터베이스 연결 실패

```bash
docker compose exec postgres pg_isready -U turtle
docker network inspect turtle-canslim_turtle-net
```

### 11.5 디스크 공간 부족

```bash
df -h

docker system prune -a
sudo truncate -s 0 /var/lib/docker/containers/*/*-json.log
```

### 11.6 앱이 시작되지 않음

```bash
docker compose logs app

docker compose config
```

환경변수 누락 여부를 확인하세요.

### 11.7 KIS API 토큰 만료

KIS API 토큰은 24시간 유효합니다. 봇이 자동으로 갱신하지만, 오래 중지했다가 재시작하면:

```bash
docker compose restart app
```

---

## 12. 보안

### 12.1 SSH 보안 강화

```bash
sudo nano /etc/ssh/sshd_config
```

```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

```bash
sudo systemctl restart sshd
```

### 12.2 자동 보안 업데이트

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 12.3 Fail2ban

```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 12.4 Security Group 최소화

- SSH(22): **My IP**로만 제한 (0.0.0.0/0 금지)
- PostgreSQL(5432), Redis(6379): 인바운드 규칙 **추가하지 않음**

### 12.5 환경변수 보안

```bash
chmod 600 .env
grep ".env" .gitignore
```

---

## 13. 프리티어 주의사항

### 13.1 프리티어 한도

| 항목 | 무료 한도 | 초과 시 |
|------|----------|--------|
| EC2 t2.micro | 750시간/월 | ~$0.0116/시간 (서울) |
| EBS (gp2) | 30 GB | ~$0.10/GB/월 |
| 데이터 전송 (Out) | 100 GB/월 | ~$0.126/GB (서울) |
| Elastic IP | 1개 (연결 시 무료) | 미연결 시 ~$3.65/월 |

### 13.2 과금 방지 체크리스트

- [ ] **인스턴스 1개만** 실행 (750시간 = 1대 x 24h x 31일)
- [ ] **EBS 30GB 이하** 유지
- [ ] **Elastic IP**는 인스턴스에 연결하거나 해제
- [ ] **CloudWatch 알림** 설정: Billing > Budgets에서 $1 초과 시 알림
- [ ] 사용 안 할 때: 인스턴스 **중지** (Stop) — Terminate는 데이터 삭제

### 13.3 비용 알림 설정

```
AWS Console > Billing > Budgets > Create Budget
- Budget type: Cost budget
- Monthly budget: $1
- Alert threshold: 80%
- Email: your@email.com
```

### 13.4 실사용 전환

| 옵션 | 방법 | 비용 |
|------|------|------|
| EC2 업그레이드 | 인스턴스 중지 → Instance Type 변경 → t3.small | ~$15/월 |
| Vultr 이전 | 새 서버에 git clone + .env 복사 + docker compose up -d | $12/월 |

---

## 부록: 빠른 시작 요약

```bash
# 1. SSH 접속
ssh -i ~/Downloads/your-key.pem ubuntu@YOUR_IP

# 2. 시스템 초기 설정
sudo apt update && sudo apt upgrade -y
sudo timedatectl set-timezone Asia/Seoul

# 3. 스왑 설정 (t2.micro 필수)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 4. Docker 설치
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 5. 프로젝트 배포
mkdir -p ~/apps && cd ~/apps
git clone https://github.com/YOUR_USERNAME/turtle-canslim.git
cd turtle-canslim

# 6. 환경변수 설정
cp .env.example .env
nano .env
chmod 600 .env
mkdir -p logs results

# 7. 빌드
docker compose build

# 8. 인프라 시작 + 마이그레이션
docker compose up -d postgres redis
docker compose run --rm --profile migrate migrate

# 9. 데몬 시작
docker compose up -d

# 10. 확인
docker compose ps
docker compose logs -f app
```

---

## 부록: 명령어 모음

```bash
# ===== 데몬 관리 =====
docker compose up -d                    # 데몬 시작 (postgres + redis + app)
docker compose down                     # 전체 중지
docker compose restart app              # 앱만 재시작
docker compose stop app                 # 앱만 중지 (graceful)
docker kill turtle-app                  # 앱 긴급 중지

# ===== 코드 업데이트 =====
git pull origin main
docker compose up -d --build            # 재빌드 + 재시작

# ===== 마이그레이션 =====
docker compose run --rm --profile migrate migrate

# ===== 빌드 캐시 문제 시 =====
docker compose build --no-cache

# ===== TUI (상태 확인) =====
docker compose run --rm --profile tui tui

# ===== 수동 스크리닝 =====
docker compose run --rm --profile screener screener

# ===== 로그 =====
docker compose logs -f app              # 실시간 로그
docker compose logs --tail=100 app      # 최근 100줄

# ===== 모니터링 =====
docker compose ps                       # 컨테이너 상태
docker stats                            # 리소스 사용량
free -h                                 # 시스템 메모리

# ===== 데이터베이스 =====
docker compose exec postgres psql -U turtle -d turtle_canslim

# ===== 정리 =====
docker system prune -a                  # 미사용 이미지/컨테이너 정리
docker volume prune                     # 미사용 볼륨 정리 (주의)
```

---

> **문서 버전**: 2.0.0
> **최종 업데이트**: 2026-02-06
> **관련 문서**: [DEPLOY.md (Vultr)](./DEPLOY.md), [SETUP.md](./SETUP.md)
