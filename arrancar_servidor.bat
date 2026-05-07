@echo off
:: 0. Tiempo de espera para red
timeout /t 10 /nobreak > NUL

:: 1. Nos movemos a la carpeta del proyecto
cd "C:\Sistema_Web_Crest"

:: 2. Arrancamos Python minimizado
start /B python app.py

:: 3. Esperamos a que Flask despierte
timeout /t 3 /nobreak > NUL

:: 4. CONFIGURAMOS EL TOKEN DE NGROK PARA ESTA SESIÓN
set NGROK_AUTHTOKEN=3CfcCJXuTAeu8BSpVaDGb0okBAh_5yZ8RRxCpJiUk2MJ6oQoS

:: 5. Arrancamos Ngrok
start /B .\ngrok.exe http --domain=hypnoses-spender-sliver.ngrok-free.dev 5000

exit