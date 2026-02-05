# Turtle-CANSLIM AWS 배포 가이드

> **최종 업데이트**: 2026-02-02  
> **대상**: AWS EC2 (Ubuntu 22.04 LTS)  
> **방식**: Docker Compose  
> **비용**: 프리티어 무료 (12개월) / 이후 t3.small ~$15/월

---

## 목차

1. [EC2 인스턴스 생성](#1-ec2-인스턴스-생성)
2. [서버 초기 설정](#2-서버-초기-설정)
3. [Docker 설치](#3-docker-설치)
4. [프로젝트 배포](#4-프로젝트-배포)
5. [서비스 실행](#5-서비스-실행)
6. [모니터링 및 관리](#6-모니터링-및-관리)
7. [문제 해결](#7-문제-해결)
8. [보안 권장사항](#8-보안-권장사항)
9. [프리티어 주의사항](#9-프리티어-주의사항)

---

## 1. EC2 인스턴스 생성

### 1.1 서버 사양

| 항목 | 프리티어 (테스트) | 실사용 권장 |
|------|-----------------|------------|
| 인스턴스 | t2.micro | t3.small |
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GB | 2 GB |
| Storage | 30 GB EBS (gp2) | 40 GB EBS (gp3) |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Region | ap-northeast-2 (서울) | ap-northeast-2 (서울) |

> **t2.micro (1GB RAM)**: 스왑 설정 필수. Paper 트레이딩 테스트용으로 충분.

### 1.2 AWS 콘솔에서 인스턴스 생성

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

### 1.3 Security Group 설정

EC2 생성 시 또는 생성 후 Security Group에서 인바운드 규칙 설정:

| Type | Port | Source | 용도 |
|------|------|--------|------|
| SSH | 22 | My IP | SSH 접속 |

> **중요**: PostgreSQL(5432), Redis(6379) 포트는 **열지 마세요**. Docker 내부 네트워크로 통신하므로 외부 노출 불필요.

### 1.4 Elastic IP 할당 (권장)

인스턴스를 중지/시작하면 Public IP가 변경됩니다. 고정 IP가 필요하면:

1. **EC2 > Elastic IPs > Allocate Elastic IP address**
2. 할당된 IP 선택 → **Associate Elastic IP address**
3. 인스턴스 선택 후 연결

> Elastic IP는 실행 중인 인스턴스에 연결되어 있으면 **무료**. 연결 안 하고 방치하면 과금됩니다.

### 1.5 SSH 접속

```bash
# .pem 파일 권한 설정 (최초 1회)
chmod 400 ~/Downloads/your-key.pem

# SSH 접속
ssh -i ~/Downloads/your-key.pem ubuntu@YOUR_ELASTIC_IP
```

> AWS EC2 Ubuntu AMI의 기본 사용자는 `ubuntu`입니다 (root 아님).

---

## 2. 서버 초기 설정

### 2.1 시스템 업데이트

```bash
sudo apt update && sudo apt upgrade -y
```

### 2.2 타임존 설정

```bash
# 한국 시간대 설정 (KRX 장 시간 기준)
sudo timedatectl set-timezone Asia/Seoul
timedatectl
```

### 2.3 스왑 설정 (필수 - t2.micro)

t2.micro는 RAM이 1GB뿐이므로 **스왑 설정이 필수**입니다.

```bash
# 2GB 스왑 파일 생성
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 재부팅 후에도 유지
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 확인
free -h
```

예상 출력:

```
              total        used        free
Mem:          981Mi       150Mi       600Mi
Swap:         2.0Gi         0B        2.0Gi
```

> **스왑 없이 실행하면 PostgreSQL + Redis + App 동시 실행 시 OOM(Out of Memory)으로 컨테이너가 죽습니다.**

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

`.env` 파일에 필요한 값:

```bash
# ===== Trading Mode =====
TRADING_MODE=paper

# ===== Database =====
POSTGRES_USER=turtle
POSTGRES_PASSWORD=YOUR_SECURE_PASSWORD_HERE
POSTGRES_DB=turtle_canslim

# ===== KIS API (Paper) =====
KIS_PAPER_APP_KEY=PSxxxxxxxxxxxxxxxx
KIS_PAPER_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIS_PAPER_ACCOUNT=50012345-01

# ===== DART API =====
DART_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ===== SEC EDGAR =====
SEC_USER_AGENT=TurtleCANSLIM your@email.com

# ===== Telegram (선택) =====
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

```bash
# .env 파일 권한 설정
chmod 600 .env
```

### 4.3 디렉토리 생성

```bash
mkdir -p logs results
```

---

## 5. 서비스 실행

### 5.1 Docker 이미지 빌드

```bash
# 이미지 빌드 (첫 실행 시 5-10분 소요)
docker compose build
```

> **t2.micro에서 빌드 시 메모리 부족할 수 있습니다.** 빌드가 실패하면 스왑이 제대로 설정되었는지 확인하세요.

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

# 최근 100줄만
docker compose logs --tail=100 app

# 로그 파일 직접 확인
tail -f ~/apps/turtle-canslim/logs/trading.log
```

### 6.2 컨테이너 상태 확인

```bash
# 실행 중인 컨테이너
docker compose ps

# 리소스 사용량 (메모리 모니터링 중요!)
docker stats
```

### 6.3 데이터베이스 접속

```bash
docker compose exec postgres psql -U turtle -d turtle_canslim

# 쿼리 예시
SELECT * FROM positions WHERE is_open = true;
\q  # 종료
```

### 6.4 재시작

```bash
# 앱만 재시작
docker compose restart app

# 이미지 재빌드 후 재시작
docker compose up -d --build
```

### 6.5 코드 업데이트 배포

```bash
cd ~/apps/turtle-canslim
git pull origin main
docker compose up -d --build
```

---

## 7. 문제 해결

### 7.1 빌드 중 메모리 부족 (Killed)

t2.micro에서 `docker compose build` 중 프로세스가 `Killed`로 종료되는 경우:

```bash
# 스왑 확인
free -h

# 스왑이 없으면 설정 (2장 참조)
# 이미 있으면 빌드 중 다른 컨테이너 중지 후 재시도
docker compose down
docker compose build
```

### 7.2 컨테이너가 OOM으로 죽음

```bash
# Docker 로그에서 OOM 확인
docker inspect turtle-app | grep -i oom

# 메모리 사용량 확인
docker stats --no-stream

# 해결: 스왑 확인 또는 인스턴스 업그레이드 검토
```

### 7.3 데이터베이스 연결 실패

```bash
# PostgreSQL 상태 확인
docker compose exec postgres pg_isready -U turtle

# 네트워크 확인
docker network inspect turtle-canslim_turtle-net
```

### 7.4 디스크 공간 부족

프리티어 EBS 30GB는 Docker 이미지가 쌓이면 부족할 수 있습니다.

```bash
# 사용량 확인
df -h

# Docker 정리
docker system prune -a

# 로그 정리
sudo truncate -s 0 /var/lib/docker/containers/*/*-json.log
```

### 7.5 SSH 접속 불가

```bash
# Security Group에서 22번 포트가 본인 IP로 열려있는지 확인
# IP가 바뀌었으면 AWS 콘솔에서 Security Group 인바운드 규칙 수정
```

### 7.6 긴급 중지

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
sudo nano /etc/ssh/sshd_config

# 권장 설정
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes

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

### 8.4 Security Group 최소화

- SSH(22): **My IP**로만 제한 (0.0.0.0/0 절대 금지)
- PostgreSQL(5432), Redis(6379): **인바운드 규칙 추가하지 않음**
- 불필요한 아웃바운드 규칙도 제거 검토

### 8.5 환경변수 보안

```bash
# .env 파일 권한
chmod 600 .env

# git에서 제외 확인
grep ".env" .gitignore
```

---

## 9. 프리티어 주의사항

AWS 프리티어는 12개월 무료지만 **한도를 초과하면 과금**됩니다.

### 9.1 프리티어 한도

| 항목 | 무료 한도 | 초과 시 |
|------|----------|--------|
| EC2 t2.micro | 750시간/월 | ~$0.0116/시간 (서울) |
| EBS (gp2) | 30 GB | ~$0.10/GB/월 |
| 데이터 전송 (Out) | 100 GB/월 | ~$0.126/GB (서울) |
| Elastic IP | 1개 (연결 시 무료) | 미연결 시 ~$3.65/월 |

### 9.2 과금 방지 체크리스트

- [ ] **인스턴스 1개만** 실행 (750시간 = 1대 × 24h × 31일)
- [ ] **EBS 30GB 이하** 유지 (스냅샷도 과금 대상)
- [ ] **Elastic IP**는 인스턴스에 연결하거나 해제 (방치 시 과금)
- [ ] **CloudWatch 알림** 설정: Billing > Budgets에서 $1 초과 시 알림
- [ ] **사용 안 할 때**: 인스턴스 중지 (Stop) — 종료(Terminate)하면 데이터 삭제됨

### 9.3 비용 알림 설정 (권장)

```
AWS Console > Billing > Budgets > Create Budget
- Budget type: Cost budget
- Monthly budget: $1
- Alert threshold: 80%
- Email: your@email.com
```

### 9.4 테스트 후 실사용 전환

모의투자 테스트 후 실거래 전환 시:

| 옵션 | 방법 | 비용 |
|------|------|------|
| **EC2 업그레이드** | 인스턴스 중지 → Instance Type 변경 → t3.small | ~$15/월 |
| **Vultr 이전** | 새 서버에 git clone + .env 복사 + docker compose up | $12/월 |

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

# 5. 프로젝트 클론
mkdir -p ~/apps && cd ~/apps
git clone https://github.com/YOUR_USERNAME/turtle-canslim.git
cd turtle-canslim

# 6. 환경변수 설정
cp .env.example .env
nano .env  # API 키 등 입력
chmod 600 .env

# 7. 디렉토리 생성
mkdir -p logs results

# 8. 빌드 및 실행
docker compose build
docker compose up -d postgres redis
docker compose run --rm migrate
docker compose up -d

# 9. 확인
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

# ===== 메모리 모니터링 (t2.micro 중요!) =====
free -h                        # 시스템 메모리
docker stats                   # 컨테이너별 사용량

# ===== 데이터베이스 =====
docker compose exec postgres psql -U turtle -d turtle_canslim
docker compose run --rm migrate  # 마이그레이션

# ===== 코드 업데이트 =====
git pull origin main && docker compose up -d --build

# ===== 정리 =====
docker system prune -a         # 미사용 이미지/컨테이너 정리
docker volume prune            # 미사용 볼륨 정리
```

---

> **문서 버전**: 1.0.0  
> **관련 문서**: [DEPLOY.md (Vultr)](./DEPLOY.md), [SETUP.md](./SETUP.md)
