@echo off
echo ============================================
echo  Crypto Arbitrage Bot - EXE 빌드
echo ============================================
echo.

pip install -r requirements.txt
echo.
echo PyInstaller로 EXE 빌드 중...
pyinstaller --onefile --console --name "CryptoArbitrageBot" ^
    --add-data "src;src" ^
    --hidden-import ccxt ^
    --hidden-import aiohttp ^
    --hidden-import colorlog ^
    --hidden-import telegram ^
    main.py

echo.
if exist dist\CryptoArbitrageBot.exe (
    echo ✅ 빌드 완료: dist\CryptoArbitrageBot.exe
    copy .env.example dist\.env.example
    echo .env.example 파일도 dist 폴더에 복사했습니다.
) else (
    echo ❌ 빌드 실패
)
echo.
pause
