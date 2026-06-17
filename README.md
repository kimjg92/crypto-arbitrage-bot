# Crypto Arbitrage Bot

Binance + Bybit 기반 저위험 암호화폐 아비트라지 봇

## 전략
1. **현물-선물 펀딩피 아비트라지** - 현물 매수 + 선물 숏으로 델타 중립 유지하며 펀딩피 수취
2. **거래소 간 차익거래** - 거래소 간 가격 차이를 이용한 동시 매수/매도

## 설치 및 실행

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. API 키 설정
```bash
copy .env.example .env
# .env 파일을 열어 API 키 입력
```

### 3. 실행
```bash
python main.py
```

### EXE 빌드 (Windows)
```bash
build_exe.bat
```

## 설정 (.env)
| 항목 | 설명 | 기본값 |
|------|------|--------|
| MAX_POSITION_USDT | 코인 1개당 최대 투자금 | 100 |
| MAX_TOTAL_USDT | 전체 최대 투자금 | 500 |
| MIN_FUNDING_RATE | 최소 펀딩피 진입 기준 (%) | 0.01 |
| MIN_ARBITRAGE_SPREAD | 최소 차익 스프레드 (%) | 0.3 |

## 주의사항
- 출금 권한 없는 API 키만 사용할 것
- 소액 테스트 후 운영 규모 확대 권장
- 거래소 점검/장애 시 자동 재시도
