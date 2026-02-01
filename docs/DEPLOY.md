# Turtle-CANSLIM 배포 가이드

> **최종 업데이트**: 2026-01-21  
> **대상**: Vultr VPS (Ubuntu 22.04+)  
> **방식**: Docker Compose

---

## 목차

1. [Vultr VPS 생성](#1-vultr-vps-생성)
2. [서버 초기 설정](#2-서버-초기-설정)
3. [Docker 설치](#3-docker-설치)
4. [프로젝트 배포](#4-프로젝트-배포)
5. [서비스 실행](#5-서비스-실행)
6. [모니터링 및 관리](#6-모니터링-및-관리)
7. [문제 해결](#7-문제-해결)
8. [보안 권장사항](#8-보안-권장사항)

---

## 1. Vultr VPS 생성

### 1.1 서버 사양 권장

| 항목 | 최소 사양 | 권장 사양 |
|------|----------|----------|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 2 GB | 4 GB |
| Storage | 40 GB SSD | 80 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Location | 서울 (한국 주식) | 서울 |

> **비용**: 약 $12~24/월 (2-4 GB RAM 기준)

### 1.2 Vultr에서 서버 생성

1. [Vultr](https://www.vultr.com/) 로그인
2. **Deploy New Server** 클릭
3. **Choose Server**: Cloud Compute (Regular Performance)
4. **Server Location**: Seoul (KRX 시장용) 또는 Los Angeles (US 시장용)
5. **Server Image**: Ubuntu 22.04 LTS x64
6. **Server Size**: 2 GB RAM / 1 vCPU ($12/mo) 이상
7. **Additional Features**: Enable IPv6 (선택)
8. **SSH Keys**: SSH 키 등록 (권장)
9. **Deploy Now** 클릭

### 1.3 SSH 접속

```bash
# 비밀번호 방식
ssh root@YOUR_SERVER_IP

# SSH 키 방식 (권장)
ssh -i ~/.ssh/your_key root@YOUR_SERVER_IP
```

---

## 2. 서버 초기 설정

### 2.1 시스템 업데이트

```bash
apt update && apt upgrade -y
```

### 2.2 사용자 생성 (보안)

```bash
# 새 사용자 생성
adduser turtle

# sudo 권한 부여
usermod -aG sudo turtle

# SSH 키 복사 (로컬에서)
ssh-copy-id -i ~/.ssh/your_key turtle@YOUR_SERVER_IP

# 새 사용자로 접속
ssh turtle@YOUR_SERVER_IP
```

### 2.3 방화벽 설정

```bash
# UFW 활성화
sudo ufw allow OpenSSH
sudo ufw allow 5432/tcp  # PostgreSQL (필요시만)
sudo ufw allow 6379/tcp  # Redis (필요시만)
sudo ufw enable
sudo ufw status
```

### 2.4 타임존 설정

```bash
# 한국 시간대 설정 (KRX 장 시간 기준)
sudo timedatectl set-timezone Asia/Seoul
timedatectl
```

---

## 3. Docker 설치

### 3.1 Docker Engine 설치

```bash
# 필수 패키지 설치
sudo apt install -y ca-certificates curl gnupg lsb-release

# Docker GPG 키 추가
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Docker 저장소 추가
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Docker 설치
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Docker 권한 설정 (sudo 없이 사용)
sudo usermod -aG docker $USER
newgrp docker

# 설치 확인
docker --version
docker compose version
```

### 3.2 Docker 자동 시작 설정

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

---

## 4. 프로젝트 배포

### 4.1 저장소 클론

```bash
# 프로젝트 디렉토리 생성
mkdir -p ~/apps
cd ~/apps

# 저장소 클론
git clone https://github.com/YOUR_USERNAME/turtle-canslim.git
cd turtle-canslim
```

### 4.2 환경변수 설정

```bash
# .env 파일 생성
cp .env.example .env
nano .env  # 또는 vim .env
```

**.env 파일 내용**:

```bash
# ===== Trading Mode =====
TRADING_MODE=paper  # paper 또는 live

# ===== Database =====
POSTGRES_USER=turtle
POSTGRES_PASSWORD=YOUR_SECURE_PASSWORD_HERE
POSTGRES_DB=turtle_canslim

# ===== KIS API (Paper) =====
KIS_PAPER_APP_KEY=PSxxxxxxxxxxxxxxxx
KIS_PAPER_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIS_PAPER_ACCOUNT=50012345-01

# ===== KIS API (Live) - 실거래 시에만 =====
KIS_LIVE_APP_KEY=
KIS_LIVE_APP_SECRET=
KIS_LIVE_ACCOUNT=

# ===== DART API =====
DART_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ===== SEC EDGAR =====
SEC_USER_AGENT=TurtleCANSLIM your@email.com

# ===== Telegram (선택) =====
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHI
TELEGRAM_CHAT_ID=123456789
```

> **중요**: `.env` 파일에 민감한 정보가 있으므로 권한 설정
> ```bash
> chmod 600 .env
> ```

### 4.3 디렉토리 생성

```bash
# 로그 및 결과 디렉토리 생성
mkdir -p logs results
```

---

## 5. 서비스 실행

### 5.1 Docker 이미지 빌드

```bash
# 이미지 빌드 (첫 실행 시 5-10분 소요)
docker compose build
```

### 5.2 데이터베이스 마이그레이션

```bash
# DB 컨테이너만 먼저 시작
docker compose up -d postgres redis

# 마이그레이션 실행 (1회만)
docker compose run --rm migrate
```

### 5.3 서비스 시작

```bash
# 전체 스택 시작 (백그라운드)
docker compose up -d

# 로그 확인
docker compose logs -f app
```

### 5.4 개별 서비스 실행

```bash
# 스크리닝만 실행 (1회성)
docker compose run --rm screener

# TUI 실행 (대화형)
docker compose run --rm --profile tui tui

# 특정 시장 스크리닝
docker compose run --rm screener python scripts/run_screener.py --market us
```

### 5.5 서비스 중지

```bash
# 전체 중지
docker compose down

# 볼륨 포함 완전 삭제 (주의: 데이터 손실)
docker compose down -v
```

---

## 6. 모니터링 및 관리

### 6.1 로그 확인

```bash
# 실시간 로그
docker compose logs -f app

# 특정 서비스 로그
docker compose logs -f postgres

# 최근 100줄만
docker compose logs --tail=100 app

# 로그 파일 직접 확인
tail -f ~/apps/turtle-canslim/logs/trading.log
```

### 6.2 컨테이너 상태 확인

```bash
# 실행 중인 컨테이너
docker compose ps

# 리소스 사용량
docker stats
```

### 6.3 데이터베이스 접속

```bash
# PostgreSQL 접속
docker compose exec postgres psql -U turtle -d turtle_canslim

# 쿼리 예시
SELECT * FROM positions WHERE is_open = true;
SELECT * FROM signals ORDER BY timestamp DESC LIMIT 10;
\q  # 종료
```

### 6.4 Redis 확인

```bash
# Redis CLI 접속
docker compose exec redis redis-cli

# 키 확인
KEYS *
GET some_key
exit
```

### 6.5 재시작

```bash
# 앱만 재시작
docker compose restart app

# 전체 재시작
docker compose restart

# 이미지 재빌드 후 재시작
docker compose up -d --build
```

---

## 7. 문제 해결

### 7.1 컨테이너가 시작되지 않음

```bash
# 로그 확인
docker compose logs app

# 환경변수 확인
docker compose config

# 컨테이너 상태 상세 확인
docker inspect turtle-app
```

### 7.2 데이터베이스 연결 실패

```bash
# PostgreSQL 상태 확인
docker compose exec postgres pg_isready -U turtle

# 네트워크 확인
docker network ls
docker network inspect turtle-canslim_turtle-net
```

### 7.3 메모리 부족

```bash
# 메모리 사용량 확인
free -h
docker stats

# 스왑 추가 (2GB RAM 서버의 경우)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 7.4 디스크 공간 부족

```bash
# 사용량 확인
df -h

# Docker 정리
docker system prune -a

# 로그 정리
sudo truncate -s 0 /var/lib/docker/containers/*/*-json.log
```

### 7.5 긴급 중지

```bash
# 트레이딩 컨테이너만 중지
docker compose stop app

# 또는 강제 종료
docker kill turtle-app
```

---

## 8. 보안 권장사항

### 8.1 SSH 보안 강화

```bash
# SSH 설정 편집
sudo nano /etc/ssh/sshd_config

# 권장 설정
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes

# SSH 재시작
sudo systemctl restart sshd
```

### 8.2 자동 보안 업데이트

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 8.3 Fail2ban 설치

```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 8.4 포트 최소화

```bash
# 외부에서 DB/Redis 접근 불필요시 포트 바인딩 제거
# docker-compose.yml에서 ports 섹션 주석 처리
```

### 8.5 환경변수 보안

```bash
# .env 파일 권한
chmod 600 .env

# git에서 제외 확인
grep ".env" .gitignore
```

---

## 부록: 빠른 시작 요약

```bash
# 1. 서버 초기 설정
apt update && apt upgrade -y
timedatectl set-timezone Asia/Seoul

# 2. Docker 설치
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 3. 프로젝트 클론
cd ~/apps
git clone https://github.com/YOUR_USERNAME/turtle-canslim.git
cd turtle-canslim

# 4. 환경변수 설정
cp .env.example .env
nano .env  # API 키 등 입력

# 5. 빌드 및 실행
docker compose build
docker compose up -d postgres redis
docker compose run --rm migrate
docker compose up -d

# 6. 확인
docker compose ps
docker compose logs -f app
```

---

## 부록: 유용한 명령어 모음

```bash
# ===== 서비스 관리 =====
docker compose up -d           # 시작
docker compose down            # 중지
docker compose restart         # 재시작
docker compose ps              # 상태 확인

# ===== 로그 =====
docker compose logs -f app     # 실시간 로그
docker compose logs --tail=50  # 최근 50줄

# ===== 스크리닝 =====
docker compose run --rm screener                                    # 국내 스크리닝
docker compose run --rm screener python scripts/run_screener.py --market us  # 미국 스크리닝

# ===== TUI =====
docker compose run --rm --profile tui tui

# ===== 데이터베이스 =====
docker compose exec postgres psql -U turtle -d turtle_canslim
docker compose run --rm migrate  # 마이그레이션

# ===== 정리 =====
docker system prune -a         # 미사용 이미지/컨테이너 정리
docker volume prune            # 미사용 볼륨 정리
```

---

> **문서 버전**: 1.0.0  
> **관련 문서**: [SETUP.md](./SETUP.md), [PROGRESS.md](./PROGRESS.md)
