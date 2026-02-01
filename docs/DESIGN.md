# Turtle-CANSLIM 자동매매 시스템 설계 문서

> **버전**: 0.6.0  
> **최종 수정**: 2026-02-01  
> **상태**: 확정

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [투자 전략](#2-투자-전략)
   - [CANSLIM 펀더멘탈 분석](#21-canslim-펀더멘탈-분석)
   - [Turtle Trading 진입/청산](#22-turtle-trading-진입청산)
3. [리스크 관리](#3-리스크-관리)
   - [2% 룰](#31-2-룰)
   - [손절가 결정](#32-손절가-결정)
   - [포지션 사이징](#33-포지션-사이징)
4. [시스템 아키텍처](#4-시스템-아키텍처)
   - [트레이딩 모드](#41-트레이딩-모드) *(모의투자/실제투자)*
   - [전체 구조](#42-전체-구조)
   - [모듈 구조](#43-모듈-구조)
5. [기술 스택](#5-기술-스택)
6. [데이터 소스](#6-데이터-소스)
7. [실행 스케줄](#7-실행-스케줄)
8. [구현 로드맵](#8-구현-로드맵)

---

## 1. 프로젝트 개요

### 1.1 목적

한국투자증권 Open API를 활용하여 국내(KRX) 및 해외(미국) 주식을 자동으로 매매하는 시스템 구축.

### 1.2 핵심 원칙

| 원칙 | 설명 |
|------|------|
| **펀더멘탈 우선** | CANSLIM으로 우량 성장주 필터링 |
| **추세 추종** | Turtle Trading으로 진입/청산 타이밍 결정 |
| **리스크 관리** | 2% 룰로 단일 거래 손실 제한 |
| **자동화** | 감정 배제, 규칙 기반 매매 |

---

## 2. 투자 전략

### 2.1 CANSLIM 펀더멘탈 분석

William O'Neil의 CANSLIM 투자법을 기반으로 우량 성장주를 스크리닝한다.

#### 2.1.1 CANSLIM 지표 정의

| 지표 | 의미 | 기준 | 비교 방식 |
|------|------|------|----------|
| **C** | Current Quarterly Earnings | 분기 EPS ≥ 20% **AND** 매출 ≥ 25% | **전년 동기 대비 (YoY)** |
| **A** | Annual Earnings Growth | 연간 EPS ≥ 20% + ROE 확인 | **전년도 vs 올해** (3년치 데이터) |
| **N** | New Products/Management/Highs | 신제품, 신경영, 신고가 | 정성적 판단 |
| **S** | Supply and Demand | 유통주식수 적정 + 거래량 증가 | 절대값 + 추세 |
| **L** | Leader or Laggard | RS(상대강도) ≥ 80 | 52주 수익률 백분위 |
| **I** | Institutional Sponsorship | 기관 보유 비율 ≥ 10% | 절대값 + 증가 추세 |
| **M** | Market Direction | 시장이 상승 추세 | 이평선 + 분배일 기반 |

#### 2.1.2 C (Current Quarterly Earnings) 상세

> ⚠️ **중요**: 직전 분기(QoQ)가 아닌 **전년 동기(YoY)** 대비로 비교해야 함

**조건**:
| 항목 | 조건 | 역할 |
|------|------|------|
| EPS 성장률 | ≥ **20%** (YoY) | **핵심 통과 기준** |
| 매출 성장률 | ≥ **25%** (YoY) | **보조 지표** (기록은 하되 통과 여부에 영향 없음) |

> ℹ️ **구현 참고**: 실제 코드에서 `c_passed`는 **EPS 성장률만으로 결정**된다.  
> 매출 성장률은 계산·기록되지만, 통과 여부 판정에는 사용되지 않는다.  
> 이는 데이터 가용성을 고려한 결정으로, 매출 데이터가 없는 종목도 평가 가능하게 한다.

```python
from decimal import Decimal

class CEarnings:
    def evaluate(
        self,
        current_eps: Decimal | None,
        previous_eps: Decimal | None,
        current_revenue: Decimal | None,
        previous_revenue: Decimal | None,
    ) -> CEarningsResult:
        """
        C 지표 검증: EPS 20% 이상 YoY 성장이 핵심 기준
        매출 성장률은 보조 지표로 기록만 함
        
        Returns:
            CEarningsResult(
                passed=True,          # EPS 기준만으로 판정
                eps_growth=0.32,      # 32%
                revenue_growth=0.28,  # 28% (보조 지표)
                reason="EPS +32.0%, Revenue +28.0%"
            )
        """
        # 데이터 유효성 검증 (previous_eps <= 0이면 실패)
        eps_growth = (current_eps - previous_eps) / previous_eps
        revenue_growth = (current_revenue - previous_revenue) / previous_revenue
        
        eps_passed = eps_growth >= self.min_eps_growth   # 20% 이상
        passed = eps_passed  # EPS만으로 통과 여부 결정
        
        return CEarningsResult(
            passed=passed,
            eps_growth=eps_growth,
            revenue_growth=revenue_growth,  # 기록용
            reason=f"EPS +{eps_growth:.1%}, Revenue +{revenue_growth:.1%}"
        )
```

**매출 성장을 보조 지표로 함께 기록하는 이유**:
- EPS만 증가하는 경우의 함정:
  - 비용 절감으로 EPS 증가 → 지속 불가능
  - 자사주 매입으로 EPS 증가 → 실질 성장 아님
  - 일회성 이익으로 EPS 증가 → 착시
- **매출 동반 성장 = 진짜 비즈니스 성장** (사용자가 후보 종목 판단 시 참고)

#### 2.1.3 A (Annual Earnings Growth) 상세

> **다년간 연간 EPS 성장률의 평균**이 기준 이상이고, **대부분 양의 성장**을 보여야 함

**조건**:
| 항목 | 조건 | 이유 |
|------|------|------|
| 평균 EPS 성장률 | ≥ **20%** (다년 평균) | 지속적 성장 |
| 양의 성장 비율 | 최근 N년 중 (N-1)년 이상 양의 성장 | 안정성 확인 |
| ROE | 함께 기록 | 자본 효율성 참고 |
| 데이터 기간 | **최소 3개년** EPS (성장률 2개 이상 산출) | 추세 파악 |

> ℹ️ **구현 참고**: `a_min_years` 설정값은 기본 **2** (최소 2개의 성장률 필요 = 3년치 EPS).  
> 단순 전년 대비가 아닌 **전체 연도별 성장률의 평균**으로 판단한다.

```python
from decimal import Decimal

class AAnnual:
    def evaluate(
        self,
        annual_eps_list: list[Decimal | None],  # 오래된 순
        roe: Decimal | None = None,
    ) -> AAnnualResult:
        """
        A 지표 검증: 다년간 평균 EPS 성장률 ≥ 20% + 대부분 양의 성장
        
        Args:
            annual_eps_list: 연간 EPS 리스트 (오래된 순, 최소 min_years+1개)
            roe: 현재 ROE (보조 지표)
        
        Returns:
            AAnnualResult(
                passed=True,
                avg_eps_growth=0.25,     # 다년 평균 25%
                yearly_growths=[0.22, 0.28],  # 연도별 성장률
                roe=0.18,
                years_of_data=3,
                reason="Avg EPS growth +25.0% over 2 years"
            )
        """
        valid_eps = [eps for eps in annual_eps_list if eps is not None]
        
        # 최소 min_years + 1개 데이터 필요 (3개년 = 성장률 2개)
        if len(valid_eps) < self.min_years + 1:
            return AAnnualResult(passed=False, reason="Insufficient data")
        
        # 연도별 성장률 계산
        yearly_growths = []
        for i in range(1, len(valid_eps)):
            if valid_eps[i - 1] <= 0:
                continue
            growth = (valid_eps[i] - valid_eps[i - 1]) / valid_eps[i - 1]
            yearly_growths.append(growth)
        
        # 평균 성장률
        avg_growth = sum(yearly_growths) / len(yearly_growths)
        
        # 최근 min_years 기간 중 대부분 양의 성장 확인
        recent_growths = yearly_growths[-self.min_years:]
        positive_years = sum(1 for g in recent_growths if g > 0)
        mostly_positive = positive_years >= max(1, len(recent_growths) - 1)
        
        # 평균 20% 이상 + 대부분 양의 성장이어야 통과
        passed = avg_growth >= self.min_eps_growth and mostly_positive
        
        return AAnnualResult(
            passed=passed,
            avg_eps_growth=avg_growth,
            yearly_growths=yearly_growths,
            roe=roe,
            years_of_data=len(valid_eps),
        )
```

**참고사항**:
- 신규상장 기업이나 정보 부족 기업은 3년치 데이터가 없을 수 있음 → 분석 제외
- ROE는 기업이 **안정적으로 돈을 벌고 있는지** 확인하는 보조 지표
- ROE = 순이익 / 자기자본 × 100 (자본 대비 수익률)
- 단순 전년 대비가 아닌 **다년 평균**을 사용하여 일시적 변동에 덜 민감

#### 2.1.4 L (Leader or Laggard) 상세 - RS Rating 계산

RS(Relative Strength) Rating은 IBD 방식으로 직접 계산한다.

**계산 방식**:
1. 전 종목의 52주(12개월) 주가 수익률 계산
2. 수익률 기준으로 전체 종목 순위 매기기
3. 백분위로 변환 (1~99)
4. RS ≥ 80 = 상위 20% 성과 종목

```python
def calculate_rs_rating(stock_prices: dict[str, pd.DataFrame]) -> dict[str, int]:
    """
    전 종목 RS Rating 계산 (1~99)
    
    Args:
        stock_prices: {종목코드: OHLCV DataFrame}
    
    Returns:
        {종목코드: RS Rating}
    """
    # 1. 각 종목의 52주 수익률 계산
    returns_52w = {}
    for code, df in stock_prices.items():
        if len(df) >= 252:  # 최소 1년치 데이터
            current_price = df['close'].iloc[-1]
            price_52w_ago = df['close'].iloc[-252]
            returns_52w[code] = (current_price - price_52w_ago) / price_52w_ago
    
    # 2. 수익률 기준 정렬 및 순위 부여
    sorted_stocks = sorted(returns_52w.items(), key=lambda x: x[1])
    total = len(sorted_stocks)
    
    # 3. 백분위 변환 (1~99)
    rs_ratings = {}
    for rank, (code, _) in enumerate(sorted_stocks):
        rs_ratings[code] = int((rank / total) * 99) + 1
    
    return rs_ratings

# 사용 예시
rs_ratings = calculate_rs_rating(all_stock_prices)
# rs_ratings['005930'] = 87  → 삼성전자 RS 87 (상위 13%)
# L 통과 조건: RS >= 80
```

**RS Rating 해석**:
| RS Rating | 의미 | 투자 적합성 |
|-----------|------|------------|
| 90~99 | 상위 1~10% | 최우선 관심 |
| 80~89 | 상위 11~20% | 관심 종목 |
| 70~79 | 상위 21~30% | 보통 |
| < 70 | 하위 70% | 부적합 (Laggard) |

#### 2.1.5 M (Market Direction) 상세 - 시장 추세 판단

O'Neil 방식의 시장 방향 판단. **M이 부정적이면 신규 진입 금지**.

**판단 기준 3가지**:

| 지표 | 상승장 | 하락장 |
|------|--------|--------|
| 이동평균선 | 지수 > 50일선, 50일선 > 200일선 | 지수 < 50일선 또는 역배열 |
| 분배일 (Distribution Day) | 최근 25일 중 < 4일 | ≥ 5일 |
| 추세 확인 | Follow-through Day 발생 | 미발생 |

```python
def judge_market_direction(index_data: pd.DataFrame) -> dict:
    """
    시장 방향 판단 (KOSPI 또는 S&P 500 기준)
    
    Returns:
        {
            'status': 'UPTREND' | 'UPTREND_PRESSURE' | 'DOWNTREND',
            'above_ma50': True,
            'above_ma200': True,
            'ma50_above_ma200': True,
            'distribution_days': 2,
            'allow_new_entry': True
        }
    """
    close = index_data['close']
    volume = index_data['volume']
    
    # 1. 이동평균선 체크
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    
    above_ma50 = close.iloc[-1] > ma50.iloc[-1]
    above_ma200 = close.iloc[-1] > ma200.iloc[-1]
    ma50_above_ma200 = ma50.iloc[-1] > ma200.iloc[-1]
    
    # 2. 분배일 카운트 (최근 25거래일)
    distribution_days = count_distribution_days(index_data, period=25)
    
    # 3. 종합 판정
    if above_ma50 and ma50_above_ma200 and distribution_days < 4:
        status = 'UPTREND'
        allow_new_entry = True
    elif above_ma50 and distribution_days < 6:
        status = 'UPTREND_PRESSURE'
        allow_new_entry = False  # 신규 진입 보수적
    else:
        status = 'DOWNTREND'
        allow_new_entry = False  # 신규 진입 금지
    
    return {
        'status': status,
        'above_ma50': above_ma50,
        'above_ma200': above_ma200,
        'ma50_above_ma200': ma50_above_ma200,
        'distribution_days': distribution_days,
        'allow_new_entry': allow_new_entry
    }


def count_distribution_days(data: pd.DataFrame, period: int = 25) -> int:
    """
    분배일 카운트
    
    분배일 정의: 지수 -0.2% 이상 하락 + 거래량 전일 대비 증가
    (기관이 물량을 분배(매도)하는 날)
    """
    recent = data.tail(period + 1)  # +1 for previous day comparison
    count = 0
    
    for i in range(1, len(recent)):
        pct_change = (recent['close'].iloc[i] - recent['close'].iloc[i-1]) / recent['close'].iloc[i-1]
        vol_increase = recent['volume'].iloc[i] > recent['volume'].iloc[i-1]
        
        if pct_change <= -0.002 and vol_increase:  # -0.2% 이상 하락
            count += 1
    
    return count
```

**시장 상태별 행동 규칙**:
| 상태 | 신규 진입 | 기존 포지션 | 현금 비중 |
|------|----------|------------|----------|
| `UPTREND` | ✅ 허용 | 유지 | 자유 |
| `UPTREND_PRESSURE` | ⚠️ 보수적 | 유지, 손절 타이트 | 확대 권장 |
| `DOWNTREND` | ❌ 금지 | 청산 고려 | 최대화 |

#### 2.1.6 추가 품질 필터

| 항목 | 기준 | 설명 |
|------|------|------|
| EPS 가속화 | 최근 2~3분기 연속 성장률 증가 | 성장 모멘텀 확인 |

#### 2.1.4 CANSLIM 점수화

```python
def calculate_canslim_score(stock_data: dict) -> dict:
    """
    각 지표별 통과 여부를 체크하고 점수화
    
    Returns:
        {
            'score': 5,  # 통과 지표 개수 (0~7)
            'passed': ['C', 'A', 'L', 'I', 'M'],
            'failed': ['N', 'S'],
            'is_candidate': True  # 5개 이상 통과 시
        }
    """
```

---

### 2.2 Turtle Trading 진입/청산

Richard Dennis의 Turtle Trading 시스템을 기반으로 매매 타이밍을 결정한다.

> **오리지널 터틀은 System 1과 System 2를 병행 사용**한다.

#### 2.2.1 진입 규칙

| 시스템 | 조건 | 청산 조건 | 특성 |
|--------|------|----------|------|
| **System 1** | 20일 고가 돌파 | 10일 저가 이탈 | 단기, 공격적 |
| **System 2** | 55일 고가 돌파 | 20일 저가 이탈 | 장기, 보수적 |

**두 시스템 병행 사용**:
- System 2가 **우선 순위가 높다** (55일 돌파이면 S2 진입)
- System 1 신호로 진입한 포지션 → System 1 청산 규칙 적용
- System 2 신호로 진입한 포지션 → System 2 청산 규칙 적용

**System 1 필터 규칙 (오리지널 터틀 방식)**:
> ⚠️ System 1은 **직전 S1 매매가 손실이었을 때만** 진입한다.  
> 직전 S1 매매가 수익이었으면 S1 돌파 신호를 무시한다.  
> (단, S2 돌파이면 S1 결과와 무관하게 진입)

이 필터의 목적은 이미 추세에 올라탄 후의 "가짜 돌파"를 걸러내는 것이다.

```python
from decimal import Decimal

class BreakoutDetector:
    def check_entry(
        self,
        current_price: Decimal,
        highs: list[Decimal],
        previous_s1_winner: bool = True,
    ) -> BreakoutResult:
        """
        System 2 먼저 확인 (우선순위), 그 다음 System 1 확인
        
        Args:
            previous_s1_winner: 직전 S1 매매의 수익 여부
                True이면 S1 진입 차단 (필터 적용)
        """
        s1_high = max(highs[-self.s1_entry_period:-1])  # 전일까지
        s2_high = max(highs[-self.s2_entry_period:-1])
        
        # System 2 우선 확인
        if current_price > s2_high:
            return BreakoutResult(type=ENTRY_S2, system=2, is_entry=True)
        
        # System 1: 직전 S1이 손실이었을 때만 진입
        if current_price > s1_high:
            if not previous_s1_winner:  # 직전 S1 매매가 손실
                return BreakoutResult(type=ENTRY_S1, system=1, is_entry=True)
        
        return BreakoutResult(type=NONE, is_entry=False)
```

#### 2.2.2 청산 규칙

| 시스템 | 조건 | 적용 대상 |
|--------|------|----------|
| **System 1** | 10일 저가 이탈 | System 1으로 진입한 포지션 |
| **System 2** | 20일 저가 이탈 | System 2로 진입한 포지션 |

> ⚠️ 손절가(2N 또는 -8%)에 먼저 도달하면 시스템 청산 규칙과 무관하게 즉시 청산

```python
def check_exit_signals(prices: pd.DataFrame) -> dict:
    """
    System 1, 2 청산 신호 확인
    
    Returns:
        {
            'system1': True/False,  # 10일 저가 이탈 여부
            'system2': True/False,  # 20일 저가 이탈 여부
        }
    """
    low = prices['low']
    close = prices['close'].iloc[-1]
    
    lowest_10 = low.rolling(10).min().shift(1).iloc[-1]
    lowest_20 = low.rolling(20).min().shift(1).iloc[-1]
    
    return {
        'system1': close < lowest_10,
        'system2': close < lowest_20,
    }
```

#### 2.2.3 N값 (ATR) 계산

```python
def calculate_n(prices: pd.DataFrame, period: int = 20) -> float:
    """
    N = 20일 ATR (Average True Range)
    
    True Range = max(
        고가 - 저가,
        |고가 - 전일종가|,
        |저가 - 전일종가|
    )
    """
    high = prices['high']
    low = prices['low']
    close = prices['close'].shift(1)
    
    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(period).mean().iloc[-1]
```

#### 2.2.4 피라미딩 (추가 매수)

기존 포지션이 수익 중일 때 추가 진입:

| 조건 | 추가 매수 |
|------|----------|
| 진입가 + 0.5N | 1st 추가 |
| 진입가 + 1.0N | 2nd 추가 |
| 진입가 + 1.5N | 3rd 추가 |

**최대 4 Units** (초기 1 + 추가 3)

---

## 3. 리스크 관리

### 3.1 2% 룰

> 한번 매매(매수부터 매도까지)할 때 내 투자자산에서 손실이 최대 2%를 넘어가지 않는다.

| 시드머니 | 최대 손실 금액 |
|----------|---------------|
| 1억원 | 200만원 |
| 5천만원 | 100만원 |
| 1천만원 | 20만원 |

**효과**:
- 연패에도 시드 보존
- 시드 증가 → 베팅 증가, 시드 감소 → 베팅 감소 (자동 조절)
- 감정적 매매 방지

### 3.2 손절가 결정

> ⚠️ **두 가지 초기 손절 기준 중 더 타이트한(높은) 가격 적용**

#### 3.2.0 손절 유형 (4가지)

| 유형 | 계산식 | 적용 시점 |
|------|--------|----------|
| **2N 손절** (`ATR_2N`) | 진입가 - (2 × N) | 초기 손절 (변동성 기반) |
| **8% 손절** (`PERCENT_8`) | 진입가 × 0.92 | 초기 손절 (고정 비율) |
| **Trailing 손절** (`TRAILING`) | 최고가 - (2 × N) | 수익 중 손절선 상향 |
| **Breakeven 손절** (`BREAKEVEN`) | 진입가 | 수익 ≥ 1N ATR일 때 본전 보장 |

> 초기 손절은 2N과 8% 중 **더 타이트한(높은)** 가격을 적용한다.  
> 이후 가격이 상승하면 **Trailing Stop**으로 손절선이 자동 상향된다.  
> 수익이 1N ATR 이상이면 **Breakeven Stop**으로 최소 본전을 보장할 수 있다.

```python
from decimal import Decimal

class StopLossCalculator:
    def calculate_initial_stop(
        self,
        entry_price: Decimal,
        atr_n: Decimal,
    ) -> StopLossResult:
        """초기 손절가 계산 (2N vs 8% 중 더 타이트한 것)"""
        stop_2n = entry_price - (self.atr_multiplier * atr_n)
        stop_percent = entry_price * (1 - self.max_percent)
        
        if stop_2n >= stop_percent:
            return StopLossResult(price=stop_2n, reason=ATR_2N)
        return StopLossResult(price=stop_percent, reason=PERCENT_8)
    
    def calculate_trailing_stop(
        self,
        highest_price: Decimal,
        atr_n: Decimal,
        current_stop: Decimal,
    ) -> StopLossResult:
        """Trailing Stop: 최고가 기준 2N, 기존 손절보다 높을 때만 갱신"""
        trailing_stop = highest_price - (self.atr_multiplier * atr_n)
        if trailing_stop > current_stop:
            return StopLossResult(price=trailing_stop, reason=TRAILING)
        return StopLossResult(price=current_stop, reason=ATR_2N)
    
    def calculate_breakeven_stop(
        self,
        entry_price: Decimal,
        current_price: Decimal,
        atr_n: Decimal,
    ) -> StopLossResult | None:
        """수익이 1N ATR 이상이면 본전 손절 활성화"""
        profit_in_atr = (current_price - entry_price) / atr_n
        if profit_in_atr >= Decimal("1.0"):
            return StopLossResult(price=entry_price, reason=BREAKEVEN)
        return None
```

#### 3.2.1 예시: 8%가 더 타이트한 경우

| 항목 | 값 |
|------|-----|
| 진입가 | 50,000원 |
| N (ATR) | 3,000원 |
| 2N 손절가 | 50,000 - 6,000 = 44,000원 |
| 8% 손절가 | 50,000 × 0.92 = 46,000원 |
| **적용 손절가** | **46,000원 (8%)** |

#### 3.2.2 예시: 2N이 더 타이트한 경우

| 항목 | 값 |
|------|-----|
| 진입가 | 50,000원 |
| N (ATR) | 1,500원 (저변동성) |
| 2N 손절가 | 50,000 - 3,000 = 47,000원 |
| 8% 손절가 | 50,000 × 0.92 = 46,000원 |
| **적용 손절가** | **47,000원 (2N)** |

### 3.3 포지션 사이징

2% 룰을 기반으로 매수 수량을 역산한다.

```python
def calculate_position_size(
    account: float,
    entry_price: float,
    stop_loss_price: float
) -> int:
    """
    2% 룰 기반 포지션 사이징
    
    Args:
        account: 총 시드머니
        entry_price: 진입가
        stop_loss_price: 손절가
    
    Returns:
        매수 수량 (정수, 내림)
    """
    max_loss = account * 0.02                        # 최대 허용 손실
    risk_per_share = entry_price - stop_loss_price   # 주당 리스크
    
    if risk_per_share <= 0:
        raise ValueError("손절가가 진입가보다 높거나 같습니다")
    
    position_size = max_loss / risk_per_share
    return int(position_size)  # 정수로 내림
```

#### 3.3.1 계산 예시

```
입력:
- 시드머니: 100,000,000원
- 진입가: 50,000원
- 손절가: 46,000원 (8% 적용)

계산:
- 최대 손실 = 100,000,000 × 0.02 = 2,000,000원
- 주당 리스크 = 50,000 - 46,000 = 4,000원
- 매수 수량 = 2,000,000 ÷ 4,000 = 500주

검증:
- 손절 시 손실 = 500주 × 4,000원 = 2,000,000원 = 시드의 2% ✅
```

### 3.4 포트폴리오 리스크 한도 (터틀 원본 방식)

터틀 원본의 **Unit 기반 한도**를 적용한다. 별도의 Heat 개념 없이 Unit 수로 총 리스크를 관리.

| 항목 | 한도 | 설명 |
|------|------|------|
| 단일 거래 리스크 | 2% | 1 Unit = 시드의 2% 리스크 |
| 종목당 최대 Unit | 4 Units | 피라미딩 한도 |
| 상관관계 높은 종목군 | 10 Units | 같은 섹터/업종 |
| 상관관계 낮은 종목군 | 16 Units | 다른 섹터 |
| **전체 포트폴리오** | **20 Units** | 최대 총 리스크 (40%) |

> **참고**: 오리지널 터틀은 선물(레버리지) 거래용으로 12 Units 한도였으나,  
> 현물 주식 거래에서는 레버리지가 없으므로 **20 Units (중립 성향)**으로 조정.

```python
RISK_LIMITS = {
    'risk_per_unit': 0.02,            # 2% (1 Unit)
    'max_units_per_stock': 4,         # 종목당 최대 (피라미딩)
    'max_units_correlated': 10,       # 상관관계 높은 종목군
    'max_units_loosely_correlated': 16,  # 상관관계 낮은 종목군
    'max_units_total': 20,            # 전체 포트폴리오 최대
}

# 최대 종목 수는 Unit 한도에서 자동 계산됨:
# - 풀 피라미딩(4 Units/종목) 시: 20 / 4 = 5개
# - 피라미딩 없이(1 Unit/종목) 시: 20 / 1 = 20개
# - 평균 2 Units/종목 시: 20 / 2 = 10개
```

#### 3.4.1 Unit 한도 예시

```
시드: 1억원
1 Unit 리스크 = 1억 × 2% = 200만원
최대 리스크 = 20 Units × 200만원 = 4,000만원 (40%)

현재 포지션:
├── 종목 A: 4 Units (풀 피라미딩)  → 리스크 800만원
├── 종목 B: 4 Units (풀 피라미딩)  → 리스크 800만원
├── 종목 C: 3 Units               → 리스크 600만원
├── 종목 D: 2 Units               → 리스크 400만원
└── 합계: 13 Units                → 총 리스크 2,600만원 (26%)

남은 여유: 20 - 13 = 7 Units
→ 신규 종목 진입 가능 (최대 7 Units까지)
→ 종목 C 추가 피라미딩 가능 (1 Unit)
```

---

## 4. 시스템 아키텍처

### 4.1 트레이딩 모드

시스템은 **모의투자**와 **실제투자** 두 가지 모드를 지원하며, 설정으로 전환 가능해야 한다.

#### 4.1.1 모드 정의

| 모드 | 설명 | 용도 |
|------|------|------|
| **PAPER** | 모의투자 (가상 계좌) | 전략 검증, 시스템 테스트 |
| **LIVE** | 실제투자 (실제 계좌) | 실거래 |

#### 4.1.2 모드별 동작 차이

| 기능 | PAPER 모드 | LIVE 모드 |
|------|-----------|-----------|
| API 엔드포인트 | 모의투자 API | 실거래 API |
| 계좌 | 모의투자 계좌 | 실제 계좌 |
| 주문 체결 | 가상 체결 (항상 성공) | 실제 체결 (시장 상황 반영) |
| 잔고 조회 | 모의 잔고 | 실제 잔고 |
| 알림 레벨 | INFO | WARNING (더 주의) |
| 서킷 브레이커 | 선택적 | 필수 |

#### 4.1.3 설정 구조

```python
from enum import Enum
from pydantic import BaseModel

class TradingMode(str, Enum):
    PAPER = "paper"  # 모의투자
    LIVE = "live"    # 실제투자

class TradingConfig(BaseModel):
    mode: TradingMode = TradingMode.PAPER  # 기본값: 모의투자
    
    # 계좌 설정 (모드별 분리)
    paper_account: str = ""      # 모의투자 계좌번호
    paper_app_key: str = ""      # 모의투자 앱키
    paper_app_secret: str = ""   # 모의투자 시크릿
    
    live_account: str = ""       # 실제 계좌번호
    live_app_key: str = ""       # 실제 앱키
    live_app_secret: str = ""    # 실제 시크릿
    
    # 안전장치
    require_confirmation_for_live: bool = True  # LIVE 전환 시 확인 필요
    max_order_amount_paper: float = float('inf')  # 모의투자 한도 없음
    max_order_amount_live: float = 10_000_000     # 실거래 단일 주문 한도

# 설정 파일 예시 (config/settings.yaml)
"""
trading:
  mode: paper  # paper | live
  
  paper:
    account: "50012345-01"
    app_key: "PSxxxxxxxx"
    app_secret: "xxxxxxxx"
  
  live:
    account: "12345678-01"
    app_key: "xxxxxxxx"
    app_secret: "xxxxxxxx"
  
  safety:
    require_confirmation_for_live: true
    max_order_amount_live: 10000000
"""
```

#### 4.1.4 Broker 인터페이스 추상화

모드에 관계없이 동일한 비동기 인터페이스 사용. 모든 금액은 `Decimal` 타입:

```python
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
    async def get_positions(self) -> list[BrokerPosition]: ...
    
    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResponse: ...
    
    @abstractmethod
    async def get_current_price(self, symbol: str) -> Decimal: ...
    
    @property
    @abstractmethod
    def is_paper_trading(self) -> bool: ...
    
    # 편의 메서드 (기본 구현 제공)
    async def buy_market(self, symbol: str, quantity: int) -> OrderResponse: ...
    async def sell_market(self, symbol: str, quantity: int) -> OrderResponse: ...
    async def buy_limit(self, symbol: str, quantity: int, price: Decimal) -> OrderResponse: ...
    async def sell_limit(self, symbol: str, quantity: int, price: Decimal) -> OrderResponse: ...


class PaperBroker(BrokerInterface):
    """모의투자 브로커 (인메모리 시뮬레이션)"""
    
    def __init__(self, initial_cash: Decimal = Decimal("100000000")):
        self._cash = initial_cash
        self._positions: dict[str, BrokerPosition] = {}  # 메모리 내 포지션
        self._orders: dict[str, BrokerOrder] = {}         # 메모리 내 주문
    
    # 모든 주문은 즉시 체결 (시장가 시뮬레이션)
    # reset() 메서드로 초기 상태 복원 가능


class LiveBroker(BrokerInterface):
    """실제투자 브로커 (한투 KIS API 연동)"""
    
    def __init__(self, settings: Settings):
        if settings.trading_mode != TradingMode.LIVE:
            raise TradingError("Cannot connect LiveBroker in PAPER mode")
        self._kis_client = KISClient(settings)
```

> ℹ️ **구현 참고**: `PaperBroker`는 한투 모의투자 API를 사용하지 않고 **완전한 인메모리 시뮬레이션**으로 동작한다.  
> 현금, 포지션, 주문을 모두 메모리에서 관리하며, `reset()`으로 초기화할 수 있다.  
> `LiveBroker`만 실제 한투 KIS API를 호출한다.

#### 4.1.5 모드 전환 안전장치

| 안전장치 | 설명 |
|----------|------|
| 환경변수 확인 | `TRADING_MODE=live` 명시적 설정 필요 |
| 확인 프롬프트 | LIVE 모드 시작 시 사용자 확인 |
| 알림 강화 | LIVE 모드에서 모든 주문에 Telegram 알림 |
| 금액 한도 | LIVE 모드 단일 주문 금액 제한 |
| 로깅 강화 | LIVE 모드 모든 주문 상세 로깅 |

```python
# 실행 시 모드 확인 로그
def log_trading_mode(config: TradingConfig):
    if config.mode == TradingMode.LIVE:
        logger.warning("=" * 50)
        logger.warning("⚠️  실제투자 모드로 실행 중입니다!")
        logger.warning(f"계좌: {config.live_account}")
        logger.warning("=" * 50)
    else:
        logger.info("📝 모의투자 모드로 실행 중입니다.")
        logger.info(f"계좌: {config.paper_account}")
```

#### 4.1.6 권장 워크플로우

```
1. 개발/테스트
   └── PAPER 모드로 기능 개발 및 단위 테스트

2. 전략 검증 (최소 3개월)
   └── PAPER 모드로 실시간 모의매매
   └── 성과 분석 및 전략 튜닝

3. 소액 실거래 테스트
   └── LIVE 모드 + 최소 금액 한도
   └── 실제 체결/슬리피지 확인

4. 본격 운용
   └── LIVE 모드 + 정상 한도
   └── 지속적 모니터링
```

---

### 4.2 전체 구조

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Turtle-CANSLIM Trading System                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────┐                                                 │
│  │  AutoDataFetcher    │                                                 │
│  │  ──────────────────│                                                 │
│  │  • 데이터 신선도 확인│                                                 │
│  │  • 자동 수집/갱신   │                                                 │
│  └───────┬─────────────┘                                                 │
│          │                                                               │
│          ▼                                                               │
│  ┌────────────────┐                                                      │
│  │  Data Layer    │                                                      │
│  │  ─────────────│                                                      │
│  │  • KIS API     │ ──▶ 시세, 주문, 계좌                                  │
│  │  • DART API    │ ──▶ 재무제표 (배치+개별)                               │
│  │  • pykrx       │ ──▶ KRX 주가/재무                                     │
│  │  • yfinance    │ ──▶ 미국 주가/재무                                     │
│  │  • SEC EDGAR   │ ──▶ 미국 재무제표 (XBRL)                              │
│  └───────┬────────┘                                                      │
│          │                                                               │
│          ▼                                                               │
│  ┌────────────────┐    ┌────────────────┐                               │
│  │  CANSLIM       │    │  Storage       │                               │
│  │  Screener      │◀──▶│  ────────────  │                               │
│  │  ─────────────│    │  • PostgreSQL  │                               │
│  │  펀더멘탈 필터  │    │  • Redis       │                               │
│  └───────┬────────┘    └────────────────┘                               │
│          │                                                               │
│          ▼                                                               │
│  ┌────────────────┐                                                      │
│  │  Turtle        │                                                      │
│  │  Signal Engine │                                                      │
│  │  ─────────────│                                                      │
│  │  진입/청산 판단 │                                                      │
│  └───────┬────────┘                                                      │
│          │                                                               │
│          ▼                                                               │
│  ┌────────────────┐                                                      │
│  │  Risk Manager  │                                                      │
│  │  ─────────────│                                                      │
│  │  • 손절가 계산  │                                                      │
│  │  • 포지션 사이징│                                                      │
│  │  • Unit 한도   │                                                      │
│  └───────┬────────┘                                                      │
│          │                                                               │
│          ▼                                                               │
│  ┌────────────────┐    ┌────────────────┐                               │
│  │  Order         │───▶│  Notification  │                               │
│  │  Executor      │    │  ─────────────│                               │
│  │  ─────────────│    │  • Telegram    │                               │
│  │  KIS API 주문  │    │  • Logging     │                               │
│  └────────────────┘    └────────────────┘                               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.3 모듈 구조

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
│   ├── data/                    # 데이터 수집
│   │   ├── __init__.py
│   │   ├── models.py            # SQLAlchemy ORM 모델
│   │   ├── repositories.py      # Repository 패턴 (DB 접근)
│   │   ├── kis_client.py        # 한투 API 클라이언트 (국내)
│   │   ├── us_client.py         # 한투 API 클라이언트 (해외 시세)
│   │   ├── dart_client.py       # DART 재무데이터 (배치+개별)
│   │   ├── sec_edgar_client.py  # SEC EDGAR 클라이언트 (미국 재무)
│   │   └── auto_fetcher.py      # 자동 데이터 수집/갱신 관리
│   │
│   ├── screener/                # CANSLIM 스크리너
│   │   ├── __init__.py
│   │   ├── canslim.py           # 국내 CANSLIM 스크리너
│   │   ├── us_canslim.py        # 미국 CANSLIM 스크리너
│   │   ├── criteria/
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
│   │   ├── turtle.py            # Turtle 메인 로직
│   │   ├── atr.py               # N값 (ATR) 계산
│   │   ├── breakout.py          # 돌파 감지 (S1 필터 포함)
│   │   └── pyramid.py           # 피라미딩 로직
│   │
│   ├── risk/                    # 리스크 관리
│   │   ├── __init__.py
│   │   ├── position_sizing.py   # 포지션 사이징 (2% 룰)
│   │   ├── stop_loss.py         # 손절가 (2N/8%/Trailing/Breakeven)
│   │   └── unit_limits.py       # Unit 한도 관리 (터틀 원본)
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
├── tests/                       # 테스트
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
├── config/
│   └── settings.yaml
│
├── docs/
│   ├── DESIGN.md               # 설계 문서 (이 문서)
│   ├── SPEC.md                 # 기술 명세서
│   ├── TASKS.md                # 태스크 목록
│   ├── PROGRESS.md             # 진행 상황
│   ├── SETUP.md                # 설정 가이드
│   └── DEPLOY.md               # 배포 가이드
│
├── scripts/
│   ├── run_screener.py          # 스크리닝 실행
│   ├── run_trading.py           # 트레이딩 실행
│   ├── run_backtest.py          # 백테스트 실행
│   ├── run_tui.py               # TUI 실행
│   └── fetch_data.py            # 데이터 수집 CLI
│
├── .env.example
├── pyproject.toml
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 5. 기술 스택

| 구성요소 | 선택 | 이유 |
|----------|------|------|
| **Language** | Python 3.11+ | 금융 라이브러리 풍부, 타입 힌트, `Decimal` 지원 |
| **Broker API** | python-kis | 한투 Open API 래퍼, WebSocket 지원 |
| **KRX 데이터** | pykrx | KRX 주가·재무 데이터 (무료, 공식 소스) |
| **US 데이터** | yfinance | 미국 주가·재무 데이터 (배치 다운로드 지원) |
| **Database** | PostgreSQL | 관계형 데이터 저장 |
| **ORM** | SQLAlchemy 2.0 (비동기) | `AsyncSession`, `Mapped` 타입 |
| **Cache** | Redis | 실시간 데이터, 세션 |
| **Scheduler** | APScheduler | 경량, 유연한 스케줄링 |
| **TUI** | Textual + Rich | 터미널 기반 사용자 인터페이스 |
| **Notification** | Telegram Bot API | 실시간, 모바일 알림 |
| **Testing** | pytest | 표준 테스트 프레임워크 |
| **Type Checking** | ruff (린팅) | 코드 품질 검사 |

> ℹ️ **Decimal 타입**: 모든 금액·가격·비율 계산에 `float` 대신 `decimal.Decimal`을 사용하여 부동소수점 오차를 방지한다.

### 5.1 주요 의존성

```toml
[project]
dependencies = [
    "python-kis>=2.1.0",        # 한투 API
    "pykrx>=1.0.0",             # KRX 주가/재무 데이터
    "yfinance>=0.2.0",          # 미국 주가/재무 데이터
    "pandas>=2.0.0",            # 데이터 처리
    "numpy>=1.24.0",            # 수치 계산
    "sqlalchemy>=2.0.0",        # ORM (비동기)
    "psycopg[binary]>=3.1.0",   # PostgreSQL
    "alembic>=1.13.0",          # DB 마이그레이션
    "redis>=5.0.0",             # Cache
    "apscheduler>=3.10.0",      # Scheduler
    "httpx>=0.25.0",            # HTTP client (비동기)
    "python-telegram-bot>=20.0", # Telegram
    "pydantic>=2.0.0",          # 데이터 검증
    "pydantic-settings>=2.0.0", # 환경 설정
    "pyyaml>=6.0.0",            # YAML 설정
    "textual>=0.40.0",          # TUI 프레임워크
    "rich>=13.0.0",             # 터미널 서식
    "structlog>=23.0.0",        # 구조화 로깅
]
```

---

## 6. 데이터 소스

### 6.1 국내 주식 (KRX)

| 데이터 | 소스 | 비고 |
|--------|------|------|
| 종목 목록/일봉 | **pykrx** | KOSPI/KOSDAQ 전종목 자동 수집 |
| 실시간 시세 | 한투 API | WebSocket 지원 |
| 재무제표 (배치) | **DART 배치 API** (`fnlttMultiAcnt`) | 다수 종목 한 번에 조회 |
| 재무제표 (개별) | DART 개별 API (`fnlttSinglAcntAll`) | 배치 실패 시 폴백 |
| 연간 EPS/BPS | **pykrx** `get_market_fundamental` | DART 보완용 |
| 기관/외인 보유 | 한투 API | Stock 모델에 저장 |
| 상대강도 (RS) | 직접 계산 | 월별 수익률 기반 |

### 6.2 해외 주식 (미국)

| 데이터 | 소스 | 비고 |
|--------|------|------|
| 종목 목록 | **SEC EDGAR** (`company_tickers_exchange.json`) | NYSE/NASDAQ 전체 |
| 시가총액 필터 | **NASDAQ Screener API** | $300M+ 필터링 |
| 일봉/재무 데이터 | **yfinance** | 배치 다운로드 (50개씩) |
| 시세/주문 | 한투 API | 해외주식 지원 |
| 재무제표 | SEC EDGAR / yfinance | XBRL companyfacts |
| 상대강도 | 직접 계산 | 월별 수익률 기반 |

### 6.3 자동 데이터 수집 (AutoDataFetcher)

`src/data/auto_fetcher.py`가 데이터 수집을 자동 관리한다:

| 기능 | 설명 |
|------|------|
| `ensure_data(market)` | 데이터 존재 여부 확인 → 없으면 자동 수집 |
| `is_data_stale(market)` | 주말 보정 포함 데이터 신선도 확인 |
| `fetch_and_store(market)` | 전체 종목 초기 로드 (종목 목록 + 1년 일봉) |
| `update_prices(market)` | 증분 업데이트 (마지막 수집일 이후) |
| `fetch_krx_financials()` | pykrx + DART 배치/개별 재무제표 수집 |
| `update_us_financials()` | yfinance 기반 미국 재무 업데이트 |
| `fetch_market_indices(market)` | KOSPI/S&P 500 지수 데이터 수집 |
| `update_stock_metadata(market)` | 유통주식수, 기관보유 메타데이터 갱신 |

### 6.3 데이터 갱신 주기

| 데이터 | 주기 |
|--------|------|
| 실시간 시세 | 실시간 (WebSocket) |
| 일봉 데이터 | 매일 장 마감 후 |
| 재무제표 | 분기별 (실적 발표 후) |
| 기관 보유 | 주간 |

---

## 7. 실행 스케줄

### 7.1 국내 주식 (KRX)

| 시간 (KST) | 작업 |
|------------|------|
| 08:00 | 전일 데이터 갱신, CANSLIM 스크리닝 |
| 08:30 | 당일 감시 종목 리스트 확정 |
| 09:00 | 장 시작, 실시간 모니터링 시작 |
| 09:00~15:20 | 돌파 신호 감지 → 주문 실행 |
| 15:30 | 장 마감, 일일 리포트 생성 |

### 7.2 해외 주식 (미국)

| 시간 (KST) | 작업 |
|------------|------|
| 21:00 | 전일 데이터 갱신, CANSLIM 스크리닝 |
| 22:00 | 감시 종목 리스트 확정 |
| 23:30 | 장 시작 (서머타임 시 22:30) |
| 23:30~06:00 | 돌파 신호 감지 → 주문 실행 |
| 06:00 | 장 마감, 일일 리포트 생성 |

---

## 8. 구현 로드맵

### Phase 1: MVP (4주)

- [ ] 프로젝트 구조 설정
- [ ] 한투 API 클라이언트 구현
- [ ] 기본 CANSLIM 스크리너 (C, A, L 지표)
- [ ] 단순 CLI 인터페이스

### Phase 2: Turtle Trading (4주)

- [ ] ATR (N값) 계산
- [ ] 돌파 진입/청산 로직
- [ ] 백테스트 프레임워크
- [ ] 과거 데이터 검증

### Phase 3: 리스크 관리 (2주)

- [ ] 손절가 계산 (2N vs 8%)
- [ ] 포지션 사이징 (2% 룰)
- [ ] 포트폴리오 Heat 관리
- [ ] 서킷 브레이커

### Phase 4: 주문 실행 (3주)

- [ ] 모의투자 연동
- [ ] 실제 주문 실행
- [ ] 주문 상태 모니터링
- [ ] 에러 핸들링

### Phase 5: 해외 주식 (3주)

- [ ] 미국 주식 시세 연동
- [ ] 해외 주식 주문
- [ ] 시간대 스케줄링
- [ ] 환율 처리

### Phase 6: 프로덕션 (4주)

- [ ] Telegram 알림
- [ ] 일일/주간 리포트
- [ ] 모니터링 대시보드
- [ ] 장애 대응 체계

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|----------|
| 0.6.0 | 2026-02-01 | 문서 현행화: C 지표 EPS만 통과 판정, A 지표 다년 평균 방식, S1 필터 규칙 추가, 4가지 손절 유형(Trailing/Breakeven 추가), Broker 인터페이스 async 전환 및 PaperBroker 인메모리 방식, AutoDataFetcher 추가, pykrx/yfinance/SEC EDGAR 데이터 소스 추가, Decimal 타입 적용, 모듈 구조 전면 업데이트 |
| 0.5.0 | 2026-01-20 | Unit 한도 20으로 조정 (현물 주식용, 중립 성향), 설계 확정 |
| 0.4.0 | 2026-01-19 | Heat 개념 삭제, 터틀 원본 Unit 한도로 변경, System 1+2 병행 사용 명시, 고정 최대 종목수 삭제 |
| 0.3.0 | 2026-01-19 | C 지표 EPS 20%/매출 25%로 수정, A 지표 20% + 전년대비 비교 + ROE 포함으로 수정 |
| 0.2.0 | 2026-01-19 | C 지표 매출 성장 조건 추가, L(RS Rating) 계산식 상세화, M(시장 방향) 판단 기준 추가, 모의투자/실제투자 모드 구분 설계 추가 |
| 0.1.0 | 2026-01-19 | 초안 작성 |

---

## 확정된 설계 사항

| 항목 | 결정 |
|------|------|
| CANSLIM C 지표 | **EPS ≥ 20% (YoY)** 만으로 통과 판정, 매출은 보조 지표로 기록만 |
| CANSLIM A 지표 | **다년간 평균 EPS 성장률 ≥ 20%** + 대부분 양의 성장 (`a_min_years=2`) |
| Turtle System | System 1 + System 2 **병행 사용** (S2 우선, S1은 직전 손실 시만 진입) |
| 리스크 관리 | **Unit 한도** 사용 (Heat 개념 없음) |
| Unit 한도 | **20 Units** (현물 주식용, 중립 성향) |
| 최대 종목 수 | Unit 한도에서 자동 계산 (풀 피라미딩 시 5개) |
| 피라미딩 | 적용, **최대 4 Units/종목** |
| 손절 | 초기: **2N 또는 -8%** 중 타이트한 것 + Trailing/Breakeven 자동 상향 |
| 트레이딩 모드 | **PAPER / LIVE** 분리 (PaperBroker = 인메모리 시뮬레이션) |
| 데이터 수집 | **AutoDataFetcher** 자동 관리 (pykrx, yfinance, DART 배치, SEC EDGAR) |
| 타입 시스템 | 모든 금액/가격/비율에 **`Decimal`** 사용 (float 미사용) |
