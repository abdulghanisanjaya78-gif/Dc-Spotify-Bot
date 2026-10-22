@echo off
cd /d "%~dp0"
if not exist .env (
  copy .env.example .env
  echo Baru dibikinin file .env - isi dulu DISCORD_TOKEN-nya pake notepad, terus jalanin lagi file ini.
  pause
  exit
)
pip install -r requirements.txt
python bot.py
pause
